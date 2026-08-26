"""Summarisation (FR-01, spec section 4.4).

Two things are enforced here that a prompt alone cannot enforce.

The sentence count. The spec requires 2 or 3 sentences, and asking politely for
that is not a control -- models drift to 1 or 5. So the count is checked in
Python, the call is retried once, and a second failure raises. It does not pad
a short summary or trim a long one, because both would be this module inventing
or destroying content to make a rule pass.

Groundedness. Every number, date, time and name in the summary is checked
against the preprocessed source (grounding.py). A summary that fails is still
returned -- with grounded=false and the offending claims listed -- because the
alternative is either hiding a result the user asked for or presenting an
unverified one as clean. The UI shows the warning inline (section 5.3).
"""

import logging
import re

from backend.orchestrator import prompts
from backend.orchestrator.cache import SUMMARY_CACHE
from backend.orchestrator.client import LLMError, get_client
from backend.orchestrator.provenance import locate
from backend.orchestrator.grounding import check_grounding
from backend.orchestrator.preprocess import preprocess
from backend.orchestrator.schemas import (
    SUMMARY_MAX_SENTENCES,
    SUMMARY_MIN_SENTENCES,
    SUMMARY_SCHEMA,
)

log = logging.getLogger(__name__)


class SummaryValidationError(LLMError):
    """The model could not produce a summary of the required shape."""


class EmptyEmailError(LLMError):
    """There is nothing left to summarise once quoting and footers are removed."""


# Sentence boundary: terminal punctuation, whitespace, then a capital or
# digit. A bare regex is not enough -- it tears "Dr. Ford" and "2 p.m. Friday"
# in half -- so candidate boundaries are filtered against known abbreviations
# and single-letter initials below.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\u0022\u2018\u201cA-Z0-9])")

# Only forms that are almost never sentence-final. Deliberately short: listing
# "pm" here made "moved to 2pm." look like an abbreviation and refuse to split,
# and "etc." / "no." end real sentences often enough to be unsafe. The dotted
# forms (a.m, p.m, e.g) are matched with their internal dots, so "at 2 p.m."
# is still protected without blocking "at 2pm.".
_ABBREVIATIONS = frozenset({
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "messrs",
    "a.m", "p.m", "e.g", "i.e", "cf", "al",
})

_TRAILING_TOKEN = re.compile(r"([A-Za-z.]+)\.$")


def _is_real_boundary(text_before):
    """False when the full stop belongs to an abbreviation or an initial."""
    match = _TRAILING_TOKEN.search(text_before)
    if not match:
        return True
    token = match.group(1).lower().rstrip(".")
    if token in _ABBREVIATIONS:
        return False
    # A single letter is an initial ("J. Smith"), not a sentence end.
    return len(token) > 1


def _split_sentences(text):
    """Split on real sentence boundaries only."""
    pieces = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        if not _is_real_boundary(text[cursor:match.start()]):
            continue
        piece = text[cursor:match.start()].strip()
        if piece:
            pieces.append(piece)
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        pieces.append(tail)
    return pieces


def _normalise_sentences(summary):
    """Flatten the model's array into one entry per actual sentence.

    The most common malformed response is not a short summary at all: it is
    two or three sentences packed into a single array element, which then
    counts as one and fails the length check. Re-splitting is honest -- it
    re-reads what the model wrote rather than adding to it.
    """
    out = []
    for entry in summary:
        if not isinstance(entry, str):
            continue
        out.extend(_split_sentences(entry.strip()))
    return out


def _validate(payload, repair=False):
    """Return the cleaned (summary, action_items), or raise ValueError.

    With repair=False the count is strict, so the model gets a fair chance (and
    a corrective retry) to produce 2-3 sentences on its own.

    With repair=True -- the final attempt -- the count is fixed deterministically
    rather than raising, because a user pressing Summarise needs a summary more
    than they need a stack trace. Repair never invents text: too many sentences
    are truncated to the first three, and a genuinely single sentence is kept as
    it stands. Nothing is padded, so a repaired summary still passes through the
    same grounding check as any other.
    """
    summary = payload.get("summary")
    if not isinstance(summary, list):
        raise ValueError("summary was not an array")

    sentences = _normalise_sentences(summary)
    if not (SUMMARY_MIN_SENTENCES <= len(sentences) <= SUMMARY_MAX_SENTENCES):
        if not repair:
            raise ValueError(
                f"summary had {len(sentences)} sentences, expected "
                f"{SUMMARY_MIN_SENTENCES} or {SUMMARY_MAX_SENTENCES}"
            )
        if len(sentences) > SUMMARY_MAX_SENTENCES:
            sentences = sentences[:SUMMARY_MAX_SENTENCES]
        elif not sentences:
            raise ValueError("summary was empty")
        # Fewer than the minimum: keep what there is. Padding would mean
        # inventing a sentence, which is the one thing never worth doing.

    raw_items = payload.get("action_items")
    if not isinstance(raw_items, list):
        raise ValueError("action_items was not an array")

    items = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise ValueError("action item was not an object")
        text = (entry.get("text") or "").strip()
        if not text:
            continue  # an empty item is nothing, not a failure
        index = entry.get("source_sentence")
        if repair and isinstance(index, int) and index > len(sentences):
            # Truncation can orphan an index; point it at the last surviving
            # sentence rather than dropping a real action item.
            index = len(sentences)
        if not isinstance(index, int) or not (1 <= index <= len(sentences)):
            # A source_sentence pointing nowhere breaks the traceability the
            # field exists to provide, so it is a validation failure, not a
            # detail to paper over.
            raise ValueError(f"action item source_sentence {index!r} is out of range")
        items.append({"text": text, "source_sentence": index})

    return sentences, items


def summarise_email(email, config, session_key=None, user=None, use_cache=True):
    """Summarise one SourceEmail. Returns the /api/summarise response body."""
    if use_cache:
        cached = SUMMARY_CACHE.get(user, email.id)
        if cached is not None:
            log.info("summarise %s: cache hit, no API call", email.id)
            return cached

    cleaned = preprocess(
        email.raw_body,
        config.token_budget_chars,
        is_html=email.is_html,
        label=f"summarise {email.id[:12]}",
    )
    if cleaned.is_empty:
        raise EmptyEmailError(
            "This email has no readable text to summarise once quoted replies "
            "and footers are removed."
        )

    client = get_client(config)
    user_prompt = prompts.summary_user(email.subject, email.sender_name, cleaned.text)

    last_error = None
    sentences = action_items = None
    payload = None

    for attempt in (1, 2):
        prompt = user_prompt
        if attempt == 2 and last_error:
            # Retry with the actual fault stated. Re-sending the identical
            # prompt and hoping for a different sample wastes the one retry the
            # budget allows.
            prompt = (
                user_prompt + '\\n\\n' +
                "Your previous response was rejected: " + str(last_error) + ". " +
                f"Return exactly {SUMMARY_MIN_SENTENCES} or {SUMMARY_MAX_SENTENCES} " +
                "sentences, each as its own element of the summary array."
            )
        payload = client.complete_json(
            system=prompts.SUMMARY_SYSTEM,
            user=prompt,
            schema_name="email_summary",
            schema=SUMMARY_SCHEMA,
            purpose="summarisation",
            session_key=session_key,
        )
        try:
            sentences, action_items = _validate(payload)
            break
        except ValueError as exc:
            last_error = exc
            log.warning("summarise %s: invalid output on attempt %d (%s)", email.id, attempt, exc)

    if sentences is None:
        # Both attempts were out of range. Repair the last response rather than
        # returning nothing: the text is the model's own, only its shape is
        # corrected, and it still faces the grounding check below.
        log.warning("summarise %s: repairing malformed summary (%s)", email.id, last_error)
        try:
            sentences, action_items = _validate(payload or {}, repair=True)
        except ValueError as exc:
            # Nothing salvageable -- an empty or non-array response. Fail loudly
            # here, because there is no summary to repair (section 3).
            raise SummaryValidationError(
                f"The model returned no usable summary after a retry ({exc})."
            ) from exc

    # The model was given the subject and sender name as well as the body, so
    # all three are legitimate sources for a claim.
    grounding_source = f"{email.subject}\n{email.sender_name}\n{cleaned.text}"
    checked = " ".join(sentences + [item["text"] for item in action_items])
    result = check_grounding(checked, grounding_source)

    if not result.grounded:
        log.info("summarise %s: %d ungrounded claim(s)", email.id, len(result.flags))

    response = {
        "email_id": email.id,
        "summary": sentences,
        "action_items": action_items,
        # Character offsets into the preprocessed body, so the UI can show
        # which passage each sentence came from. Computed deterministically
        # here, never asked of the model (rule 5).
        "provenance": locate(sentences, cleaned.text),
        "grounded": result.grounded,
        "ungrounded_flags": result.as_api_flags(),
    }

    if use_cache:
        # Model output only. The body is not cached and does not outlive this
        # function (NFR-03).
        SUMMARY_CACHE.set(user, email.id, response)
    return response
