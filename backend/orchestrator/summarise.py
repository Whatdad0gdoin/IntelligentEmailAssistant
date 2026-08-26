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


def _validate(payload):
    """Return the cleaned (summary, action_items), or raise ValueError.

    Raising rather than repairing is the point. A summary trimmed from five
    sentences to three is not the model's answer any more, and a summary padded
    from one to two would have to invent the padding.
    """
    summary = payload.get("summary")
    if not isinstance(summary, list):
        raise ValueError("summary was not an array")

    sentences = [s.strip() for s in summary if isinstance(s, str) and s.strip()]
    if not (SUMMARY_MIN_SENTENCES <= len(sentences) <= SUMMARY_MAX_SENTENCES):
        raise ValueError(
            f"summary had {len(sentences)} sentences, expected "
            f"{SUMMARY_MIN_SENTENCES} or {SUMMARY_MAX_SENTENCES}"
        )

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
    for attempt in (1, 2):
        payload = client.complete_json(
            system=prompts.SUMMARY_SYSTEM,
            user=user_prompt,
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
    else:
        # Fail loudly (section 3). No half-summary is returned.
        raise SummaryValidationError(
            f"The model did not return a valid {SUMMARY_MIN_SENTENCES}-to-"
            f"{SUMMARY_MAX_SENTENCES} sentence summary after a retry ({last_error})."
        )

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
