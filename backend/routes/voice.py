"""POST /api/voice/intent (FR-05, spec section 6.3).

Takes a transcript from the browser's speech recognition and returns which of
three actions the user meant -- or `unknown`, which is a valid outcome and not
a failure. The frontend responds to `unknown` and to low confidence by showing
the transcript back and asking the user to choose (section 6.3).

This route does speech *intent* only. Recognition itself happens in the
browser: the audio never reaches the server, which is both a privacy property
worth having and the reason no audio format appears anywhere in this codebase.
"""

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
    candidates = []
    raw_candidates = body.get("emails")
    if raw_candidates is not None:
        if not isinstance(raw_candidates, list):
            raise BadRequest("'emails' must be an array if provided.")
        for entry in raw_candidates[:MAX_CANDIDATES]:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            candidates.append({
                "id": entry["id"],
                "sender_name": (entry.get("sender_name") or "")[:200],
                "subject": (entry.get("subject") or "")[:200],
            })

    return jsonify(
        classify_intent(
            transcript,
            config(),
            session_key=session_key(),
            candidates=candidates,
        )
    ), 200
