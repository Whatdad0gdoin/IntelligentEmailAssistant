"""POST /api/voice/intent (FR-05, spec section 6.3).

Takes a transcript from the browser's speech recognition and returns which of
three actions the user meant -- or `unknown`, which is a valid outcome and not
a failure. The frontend responds to `unknown` and to low confidence by showing
the transcript back and asking the user to choose (section 6.3).

This route does speech *intent* only. Recognition is the browser's Web Speech
API and only its transcript is posted here, so this server never receives
audio -- a privacy property worth having, and the reason no audio format
appears anywhere in this codebase. It is not a promise that the audio stays on
the user's device: Chrome's recogniser sends it to Google unless on-device
recognition is in use, and Edge's sends it to Microsoft. The Voice view says so
rather than claiming more than the app controls.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from backend.orchestrator.intent import classify_intent
from backend.routes.support import (
    BadRequest,
    config,
    handle_errors,
    json_body,
    session_key,
)

bp = Blueprint("voice", __name__, url_prefix="/api/voice")

MAX_TRANSCRIPT_CHARS = 500
MAX_CANDIDATES = 100
MAX_ALTERNATIVES = 5
# How many `emails` entries are read before the newest MAX_CANDIDATES are kept.
# Twice the Gmail API adapter's 500-message cap, so a mailbox from it is read
# whole; bounded at all because every other input to this route is.
MAX_CANDIDATES_READ = 1000


def _received_time(value):
    """Seconds since the epoch for an ISO-8601 timestamp, or None.

    None for anything missing or unparseable: an email with no usable date is
    ordered last rather than guessed into place. A timestamp with no offset is
    read as UTC, which is how the adapters write them.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _newest_first(dated, undated):
    """Dated candidates newest first, then the undated ones.

    Python's sort is stable, reverse=True included, so emails with the same
    timestamp keep the order the caller sent them in.
    """
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return [candidate for _, candidate in dated] + undated


@bp.post("/intent")
@handle_errors
def intent():
    body = json_body()

    transcript = body.get("transcript")
    if not isinstance(transcript, str):
        raise BadRequest("'transcript' is required.")
    transcript = transcript.strip()[:MAX_TRANSCRIPT_CHARS]

    # Optional, and additive to the documented contract. The response needs a
    # `target_email_id`, but an id is parsed data and rule 5 keeps parsed data
    # away from the model -- so the model never sees or produces one. Instead
    # the caller may pass the emails currently on screen, and the backend
    # matches the spoken reference against their sender names and subjects
    # deterministically. Omit it and `target_email_id` is simply null, which
    # the contract already allows.
    #
    # Order matters twice: the resolver reads the first candidate as the newest
    # ("summarise the latest email"), and only the first MAX_CANDIDATES are
    # kept. The frontend once sent the inbox in category order, so "the latest
    # email" meant the newest Work email and a long inbox lost whole categories
    # to the cap. So each entry may also carry `received_at` (ISO-8601), and
    # when it does the route orders the list itself instead of trusting the
    # order it arrived in. Without it the caller's order stands, as before.
    candidates = []
    raw_candidates = body.get("emails")
    if raw_candidates is not None:
        if not isinstance(raw_candidates, list):
            raise BadRequest("'emails' must be an array if provided.")
        dated, undated = [], []
        for entry in raw_candidates[:MAX_CANDIDATES_READ]:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            candidate = {
                "id": entry["id"],
                "sender_name": (entry.get("sender_name") or "")[:200],
                "subject": (entry.get("subject") or "")[:200],
            }
            received = _received_time(entry.get("received_at"))
            if received is None:
                undated.append(candidate)
            else:
                dated.append((received, candidate))
        candidates = _newest_first(dated, undated)[:MAX_CANDIDATES]

    # Also optional. The browser's recogniser ranks several hypotheses for the
    # same utterance, and the top one is often not the one that caught the
    # name. Pooling them widens the deterministic match without widening what
    # the model sees: intent is still classified from the primary transcript
    # alone, and alternatives only feed target resolution.
    alternatives = []
    raw_alternatives = body.get("alternatives")
    if raw_alternatives is not None:
        if not isinstance(raw_alternatives, list):
            raise BadRequest("'alternatives' must be an array if provided.")
        for entry in raw_alternatives[:MAX_ALTERNATIVES]:
            if isinstance(entry, str) and entry.strip():
                alternatives.append(entry.strip()[:MAX_TRANSCRIPT_CHARS])

    return jsonify(
        classify_intent(
            transcript,
            config(),
            session_key=session_key(),
            candidates=candidates,
            alternatives=alternatives,
        )
    ), 200
