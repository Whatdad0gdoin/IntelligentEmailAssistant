"""Categorisation (FR-02, spec section 4.3).

Three defences sit between the model and a label reaching the inbox:

1. The category is an enum in the JSON schema, so a fifth category is
   unrepresentable rather than merely discouraged.
2. The model must quote verbatim evidence, and that span is checked against the
   source text. A fabricated span means the label is discarded.
3. Confidence below the configured threshold is discarded too.

Anything discarded goes to Review. Review is a real, visible bucket in the
inbox, not a quiet fallback to Work: an email in the wrong category has been
silently hidden from the user, while an email in Review has been honestly
handed back to them. The second failure is much cheaper than the first.

ONE EMAIL PER CALL, CALLS IN PARALLEL

This module used to send the whole inbox in one request (section 3), on the
reasoning that one round trip beats N. Measured, it was the wrong trade. On the
held-out test split (n=215, eval/data/compare/, 2026-10-06), the same prompt,
schema, verifier and threshold with one email per call instead of twenty took
strict accuracy from 77.7% to 90.7% -- 34 rows gained, 6 lost, exact McNemar
p<0.001 -- misfiled emails from 28 to 15, Review from 20 to 5, and
quote-verification failures from 15 to 2. Twenty emails in one prompt bleed
into each other, and the evidence check catches it the only way it can: by
throwing the label away.

Batching also left a hole. Every email in a batch shares one prompt, so an
email's body can forge the <email id="..."> delimiter and answer for another
email in the batch, and _verify keeps the first result per id. With one email
per call, a result for any other id is discarded as unrequested, so that
channel is closed rather than merely unlikely.

What it costs is tokens and, unless the calls overlap, time. The instructions
are re-sent with every email, which on the configured model moves $0.06 to
$0.15 per 1,000 emails. One 20-email call takes 8.5 s at p50 and a single-email call
1.0 s, so a cold inbox load is only faster if the calls run concurrently --
hence the thread pool below.

CLASSIFY_BATCH_SIZE=20 restores the batched behaviour. Chunks of any size take
the same path, the same verification and the same Review routing.
"""

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from backend.orchestrator import prompts
from backend.orchestrator.budget import get_budget
from backend.orchestrator.cache import CLASSIFY_CACHE
from backend.orchestrator.client import LLMError, LLMUnavailable, get_client
from backend.orchestrator.preprocess import preprocess
from backend.orchestrator.grounding import verify_evidence
from backend.orchestrator.schemas import CATEGORIES, CLASSIFY_SCHEMA, REVIEW_CATEGORY

log = logging.getLogger(__name__)

# Why an email ended up in Review. Logged for evaluation; not returned to the
# client, which only needs to know the label is unverified (section 5.2).
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_EVIDENCE_NOT_FOUND = "evidence_not_in_source"
REASON_MISSING_FROM_RESPONSE = "missing_from_model_response"
REASON_EMPTY_EMAIL = "no_text_to_classify"
REASON_UNKNOWN_CATEGORY = "category_outside_enum"
# The two below are not judgements about the email at all. Their labels are
# never cached, so the next inbox load asks again.
REASON_CALL_FAILED = "model_call_failed"
REASON_NOT_SENT = "not_sent_after_slow_service_failure"

# The per-session allowance (MAX_REQUESTS_PER_SESSION, see budget.py) was set
# when one call classified a batch of up to 20 emails. Charged per call, the
# per-email design would make a 25-email cold load cost 25 units instead of 2,
# and the cap would start cutting off ordinary use rather than runaway loops.
# So the unit of classification stays what it was -- 20 emails -- whatever the
# batch size: it is charged once, up front, before any call goes out (so a
# session over its allowance still cannot spend), and the calls themselves pass
# session_key=None so the client does not charge them a second time.
#
# One consequence, stated rather than hidden: the client's single retry is not
# charged here either. That is bounded -- at most two attempts per call, and
# the number of calls is bounded by the request (GMAIL_LIMIT on the inbox,
# MAX_BATCH on /api/classify) -- and the cap is a guard rail, not a meter.
BUDGET_EMAILS_PER_UNIT = 20

# Marks a chunk whose call was never made (see _call_chunk).
_NOT_SENT = object()


def _review(email_id, confidence=0.0, evidence=""):
    return {
        "id": email_id,
        "category": REVIEW_CATEGORY,
        "confidence": round(float(confidence or 0.0), 3),
        "evidence": evidence,
    }


def _clamp(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def classify_emails(items, config, session_key=None, user=None, use_cache=True,
                    preprocessed=False, review_reasons=None):
    """Classify emails. Returns one result per input, in input order.

    `items` are dicts of {id, subject, body}. By default `body` is raw text and
    is preprocessed here. With preprocessed=True the caller has already run
    preprocess() and `body` is the cleaned text; /api/inbox does this because
    it needs the cleaned text for the snippet anyway, and running the HTML
    strip and quote-chain regexes twice per email per page load was pure waste.
    Either way, body text never leaves this call.

    Emails the cache cannot answer are cut into chunks of CLASSIFY_BATCH_SIZE,
    one model call each, with up to CLASSIFY_CONCURRENCY calls in flight. A
    call that fails costs only its own chunk: those emails go to Review,
    uncached, so the next load asks again. The request itself fails only when
    no call succeeded and the service was the reason (LLMUnavailable, a 503 at
    the route) -- an inbox that is entirely Review because the API is down
    would present an outage as a mailbox full of abstentions.

    `review_reasons`, when given a dict, is filled with {id: reason} for every
    email this call routed to Review. eval/evaluate_classifier.py needs it to
    tell an abstention from a failed call; the routes do not pass it, and the
    results -- the API contract -- do not carry it.
    """
    if not items:
        return []

    reasons = review_reasons if review_reasons is not None else {}
    ordered_ids = [item["id"] for item in items]
    results = {}
    pending = []
    sources = {}

    for item in items:
        email_id = item["id"]
        if email_id in sources:
            # The same id twice is one email. With one call per email a
            # duplicate would be paid for twice, and the evidence would be
            # checked against whichever copy happened to come last.
            continue
        subject = item.get("subject") or ""
        body = item.get("body") or ""
        if preprocessed:
            body_text = body
            body_empty = not body.strip()
        else:
            cleaned = preprocess(body, config.token_budget_chars, label=f"classify {email_id[:12]}")
            body_text = cleaned.text
            body_empty = cleaned.is_empty
        # Evidence may legitimately be quoted from the subject line, so the
        # subject is part of the text the span is checked against.
        sources[email_id] = subject + chr(10) + body_text

        if use_cache:
            cached = CLASSIFY_CACHE.get(user, email_id)
            if cached is not None:
                results[email_id] = cached
                continue

        if not subject.strip() and body_empty:
            log.info("classify %s -> Review (%s)", email_id, REASON_EMPTY_EMAIL)
            results[email_id] = _review(email_id)
            reasons[email_id] = REASON_EMPTY_EMAIL
            continue

        pending.append({"id": email_id, "subject": subject, "body": body_text})

    if pending:
        # Before any call: see BUDGET_EMAILS_PER_UNIT.
        get_budget(config).spend(
            session_key, cost=math.ceil(len(pending) / BUDGET_EMAILS_PER_UNIT)
        )

        size = config.classify_batch_size
        chunks = [pending[start:start + size] for start in range(0, len(pending), size)]
        outcomes = _run_chunks(chunks, config)
        _raise_if_the_service_is_down(outcomes)

        failed = []
        for chunk, (response, error) in zip(chunks, outcomes):
            if error is not None:
                failed.append((chunk, error))
                continue
            for verified, reason in _verify(response, chunk, sources, config):
                results[verified["id"]] = verified
                if reason:
                    reasons[verified["id"]] = reason
                if use_cache:
                    CLASSIFY_CACHE.set(user, verified["id"], verified)
            _route_dropped(chunk, results, reasons)

        if failed:
            _route_failed(failed, len(chunks), reasons)

    # Every id still owed an answer -- dropped by the model, or in a chunk
    # whose call failed -- gets one. Reasons were logged where they arose.
    for email_id in ordered_ids:
        if email_id not in results:
            results[email_id] = _review(email_id)

    return [results[email_id] for email_id in ordered_ids]


def _run_chunks(chunks, config):
    """One model call per chunk, up to CLASSIFY_CONCURRENCY at once.

    Returns a (response, error) pair per chunk, in chunk order. Calls finish in
    whatever order the network decides, so nothing downstream may depend on it;
    results are matched back by id.

    A thread pool rather than asyncio because the SDK client and everything
    around it are synchronous, and the work is waiting on the network: the
    threads spend their time blocked on sockets, not holding the GIL. The pool
    lives for one request. A shared pool would cap concurrency across users,
    but it would also queue one user's cold load behind another's.
    """
    client = get_client(config)
    # Set when a call fails slowly; calls not yet started are then not sent.
    # See _call_chunk for why only a slow failure counts.
    stop = threading.Event()
    slow = config.latency_target_seconds
    workers = min(config.classify_concurrency, len(chunks))

    if workers <= 1:
        return [_call_chunk(client, chunk, stop, slow) for chunk in chunks]

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="classify") as pool:
        futures = [pool.submit(_call_chunk, client, chunk, stop, slow) for chunk in chunks]
        return [future.result() for future in futures]


def _call_chunk(client, chunk, stop, slow_seconds):
    """Make one call. Returns (response, None) or (None, why it has none)."""
    if stop.is_set():
        return None, _NOT_SENT
    started = time.perf_counter()
    try:
        return client.complete_json(
            system=prompts.CLASSIFY_SYSTEM,
            user=prompts.classify_user(chunk),
            schema_name="email_classification",
            schema=CLASSIFY_SCHEMA,
            purpose="classification",
            # Already charged, in 20-email units, by classify_emails.
            session_key=None,
        ), None
    except LLMUnavailable as exc:
        # Only a slow failure stops the queue. One that took longer than the
        # whole NFR-01 budget (LATENCY_TARGET_SECONDS) was waiting on a timeout
        # or a back-off, and the calls behind it would wait the same way: with
        # the API timing out, each takes 45 s (two 20 s attempts and the pause
        # between them), and a 25-email inbox behind 8 workers would hold the
        # request for three minutes to report what the first failure had
        # already shown. A fast failure -- a request the API rejected outright,
        # say -- costs little to repeat, and stopping on it would send the rest
        # of the inbox to Review because of a single email, on every load.
        if time.perf_counter() - started >= slow_seconds:
            stop.set()
        return None, exc
    except LLMError as exc:
        # Refused, unparseable or off-schema: a verdict on this chunk's
        # emails, not on the service, so the other calls carry on.
        return None, exc
    except BaseException:
        # Not a failed call but a bug. Stop spending on answers no one will
        # read, and let it surface as one.
        stop.set()
        raise


def _raise_if_the_service_is_down(outcomes):
    """Fail the request if no call succeeded and the service was why.

    Kept as the user-visible behaviour from the single-call design: the route
    maps LLMUnavailable to 503 and the inbox shows "The AI service is
    unavailable". Without this, an outage would arrive as an inbox in which
    every email had been honestly handed back for review -- true of each email,
    false about the cause.

    Calls that all failed on their content (refused, unparseable) do not raise.
    Those labels are never cached, so a single email the model always refuses
    would be the only uncached one on every later load, and raising would
    take the whole inbox down with it each time.
    """
    if any(error is None for _, error in outcomes):
        return
    outage = next((e for _, e in outcomes if isinstance(e, LLMUnavailable)), None)
    if outage is None:
        return
    log.warning(
        "classify: no model call in this request succeeded (%d calls); reporting "
        "the service failure rather than routing every email to Review.",
        len(outcomes),
    )
    raise outage


def _route_dropped(chunk, results, reasons):
    """Record the ids a successful call did not answer for."""
    dropped = [item["id"] for item in chunk if item["id"] not in results]
    for email_id in dropped:
        log.info("classify %s -> Review (%s)", email_id, REASON_MISSING_FROM_RESPONSE)
        reasons[email_id] = REASON_MISSING_FROM_RESPONSE

    # Routing a dropped id to Review is the right outcome -- better an honest
    # "unsorted" than a guessed label. But losing a large share of one batch is
    # not a per-email event, it is a failed request that still returned 200,
    # and at info level it was invisible: a run in eval/data/dev_preds.csv lost
    # 17 of one 20-email batch and nobody noticed until the file would not
    # reconcile. One warning per batch makes that legible at a glance.
    if dropped:
        log.warning(
            "classify: the model returned no result for %d of %d emails in this "
            "batch; they were routed to Review. A large share suggests a "
            "truncated or malformed response rather than %d individual "
            "judgements.",
            len(dropped), len(chunk), len(dropped),
        )


def _route_failed(failed, total_calls, reasons):
    """Record the emails whose call failed or was never made.

    One warning per request, naming error types only: an exception message can
    carry request content, and these are logged where NFR-03 applies.
    """
    errors = sorted({type(error).__name__ for _, error in failed if error is not _NOT_SENT})
    not_sent = sum(1 for _, error in failed if error is _NOT_SENT)
    emails = 0
    for chunk, error in failed:
        reason = REASON_NOT_SENT if error is _NOT_SENT else REASON_CALL_FAILED
        for item in chunk:
            log.info("classify %s -> Review (%s)", item["id"], reason)
            reasons[item["id"]] = reason
            emails += 1
    log.warning(
        "classify: %d of %d model calls failed (%s) and %d were not sent; their "
        "%d emails were routed to Review uncached, so the next load retries them.",
        len(failed) - not_sent, total_calls, ", ".join(errors) or "none",
        not_sent, emails,
    )


def _verify(response, pending, sources, config):
    """Apply the section 4.3 checks to each returned label.

    Yields (result, reason): reason is None for a label that stands, otherwise
    why the email was sent to Review.
    """
    requested = {item["id"] for item in pending}
    threshold = config.classify_confidence_threshold
    seen = set()

    for raw in (response or {}).get("results", []):
        email_id = (raw or {}).get("id")
        # An id we never asked about is not a result; it is noise, and
        # accepting it would let a model relabel an email outside the batch --
        # or let one email's body, posing as another's delimiter, do it.
        if email_id not in requested or email_id in seen:
            log.warning("classify: discarding result for unrequested or duplicate id")
            continue
        seen.add(email_id)

        category = raw.get("category")
        confidence = _clamp(raw.get("confidence"))
        evidence = (raw.get("evidence") or "").strip()

        if category not in CATEGORIES:
            # The schema should make this impossible. Checked anyway, because
            # "should be impossible" is not a guarantee.
            log.warning("classify %s -> Review (%s)", email_id, REASON_UNKNOWN_CATEGORY)
            yield _review(email_id, confidence), REASON_UNKNOWN_CATEGORY
            continue

        if not verify_evidence(evidence, sources.get(email_id, "")):
            log.info("classify %s -> Review (%s)", email_id, REASON_EVIDENCE_NOT_FOUND)
            # The span is dropped, not returned: it did not come from the email,
            # so showing it to the user would present a fabrication as a quote.
            yield _review(email_id, confidence), REASON_EVIDENCE_NOT_FOUND
            continue

        if confidence < threshold:
            log.info(
                "classify %s -> Review (%s: %.2f < %.2f)",
                email_id, REASON_LOW_CONFIDENCE, confidence, threshold,
            )
            yield _review(email_id, confidence, evidence), REASON_LOW_CONFIDENCE
            continue

        yield {
            "id": email_id,
            "category": category,
            "confidence": round(confidence, 3),
            "evidence": evidence,
        }, None
