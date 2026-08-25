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

One batch request covers the whole inbox (section 3), which is one round trip
on login rather than one per email.
"""

import logging

from backend.orchestrator import prompts
from backend.orchestrator.cache import CLASSIFY_CACHE
from backend.orchestrator.client import get_client
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


def classify_emails(items, config, session_key=None, user=None, use_cache=True):
    """Classify a batch. Returns one result per input, in input order.

    `items` are dicts of {id, subject, body} carrying raw body text. Bodies are
    preprocessed here and never leave this call.
    """
    if not items:
        return []

    ordered_ids = [item["id"] for item in items]
    results = {}
    pending = []
    sources = {}

    for item in items:
        email_id = item["id"]
        subject = item.get("subject") or ""
        cleaned = preprocess(
            item.get("body") or "", config.token_budget_chars, label=f"classify {email_id[:12]}"
        )
        # Evidence may legitimately be quoted from the subject line, so the
        # subject is part of the text the span is checked against.
        sources[email_id] = f"{subject}\n{cleaned.text}"

        if use_cache:
            cached = CLASSIFY_CACHE.get(user, email_id)
            if cached is not None:
                results[email_id] = cached
                continue

        if not subject.strip() and cleaned.is_empty:
            log.info("classify %s -> Review (%s)", email_id, REASON_EMPTY_EMAIL)
            results[email_id] = _review(email_id)
            continue

        pending.append({"id": email_id, "subject": subject, "body": cleaned.text})

    if pending:
        response = get_client(config).complete_json(
            system=prompts.CLASSIFY_SYSTEM,
            user=prompts.classify_user(pending),
            schema_name="email_classification",
            schema=CLASSIFY_SCHEMA,
            purpose="classification",
            session_key=session_key,
        )
        for verified in _verify(response, pending, sources, config):
            results[verified["id"]] = verified
            if use_cache:
                CLASSIFY_CACHE.set(user, verified["id"], verified)

    # Any id the model dropped is still owed an answer.
    for email_id in ordered_ids:
        if email_id not in results:
            log.info("classify %s -> Review (%s)", email_id, REASON_MISSING_FROM_RESPONSE)
            results[email_id] = _review(email_id)

    return [results[email_id] for email_id in ordered_ids]


def _verify(response, pending, sources, config):
    """Apply the section 4.3 checks to each returned label."""
    requested = {item["id"] for item in pending}
    threshold = config.classify_confidence_threshold
    seen = set()

    for raw in (response or {}).get("results", []):
        email_id = (raw or {}).get("id")
        # An id we never asked about is not a result; it is noise, and
        # accepting it would let a model relabel an email outside the batch.
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
            yield _review(email_id, confidence)
            continue

        if not verify_evidence(evidence, sources.get(email_id, "")):
            log.info("classify %s -> Review (%s)", email_id, REASON_EVIDENCE_NOT_FOUND)
            # The span is dropped, not returned: it did not come from the email,
            # so showing it to the user would present a fabrication as a quote.
            yield _review(email_id, confidence)
            continue

        if confidence < threshold:
            log.info(
                "classify %s -> Review (%s: %.2f < %.2f)",
                email_id, REASON_LOW_CONFIDENCE, confidence, threshold,
            )
            yield _review(email_id, confidence, evidence)
            continue

        yield {
            "id": email_id,
            "category": category,
            "confidence": round(confidence, 3),
            "evidence": evidence,
        }
