"""The three AI feature routes: summarise, classify, draft.

Kept in one blueprint because they are the same four lines each -- read the
request, look the email up in the adapter, hand it to an orchestrator module,
return what comes back. All the behaviour that matters (preprocessing, schema
constraints, evidence checks, grounding, caching, retries, the request cap)
lives in backend/orchestrator. Nothing here knows the model name, and nothing
here imports the vendor SDK (spec rule 4).

There is deliberately no send route. See the module note on draft() below.
"""

from flask import Blueprint, jsonify

from backend.adapters.email_source import get_email_source
from backend.orchestrator.classify import classify_emails
from backend.orchestrator.draft import draft_reply
from backend.orchestrator.schemas import DEFAULT_TONE, TONES
from backend.orchestrator.summarise import summarise_email
from backend.routes.support import (
    BadRequest,
    EmailNotFound,
    config,
    current_user,
    handle_errors,
    json_body,
    required_string,
    session_key,
)

bp = Blueprint("ai", __name__, url_prefix="/api")

# One /api/classify call carries a whole inbox, not a whole mail server.
MAX_BATCH = 100
MAX_BODY_CHARS = 100_000


def _load_email(email_id):
    message = get_email_source(config()).get_email(email_id)
    if message is None:
        # A real multi-account source scopes the lookup by user inside the
        # adapter, so by the time a lookup misses here it genuinely is "no such
        # message" rather than "not yours".
        raise EmailNotFound(f"No email with id {email_id}.")
    return message


@bp.post("/summarise")
@handle_errors
def summarise():
    """FR-01. Returns a 2-3 sentence summary with grounding flags."""
    body = json_body()
    email_id = required_string(body, "email_id", max_length=256)
    message = _load_email(email_id)

    return jsonify(
        summarise_email(
            message,
            config(),
            session_key=session_key(),
            user=current_user(),
        )
    ), 200


@bp.post("/classify")
@handle_errors
def classify():
    """FR-02. Batch endpoint: one call for the inbox, not one per email.

    Takes bodies in the request rather than ids so the evaluation notebook can
    score the classifier over a labelled dataset (DR-01) without that dataset
    having to exist as a mailbox.
    """
    body = json_body()
    emails = body.get("emails")
    if not isinstance(emails, list):
        raise BadRequest("'emails' must be an array.")
    if not emails:
        return jsonify({"results": []}), 200
    if len(emails) > MAX_BATCH:
        raise BadRequest(f"Too many emails in one batch (limit {MAX_BATCH}).")

    items = []
    for entry in emails:
        if not isinstance(entry, dict):
            raise BadRequest("Each email must be an object.")
        email_id = entry.get("id")
        if not isinstance(email_id, str) or not email_id.strip():
            raise BadRequest("Each email needs a string 'id'.")
        items.append({
            "id": email_id.strip(),
            "subject": (entry.get("subject") or "")[:1000],
            "body": (entry.get("body") or "")[:MAX_BODY_CHARS],
        })

    return jsonify({
        "results": classify_emails(
            items,
            config(),
            session_key=session_key(),
            user=current_user(),
            # Bodies supplied in the request are not necessarily the mailbox's
            # bodies, so caching them against an email id would let an
            # evaluation run poison the inbox's labels.
            use_cache=False,
        )
    }), 200


@bp.post("/draft")
@handle_errors
def draft():
    """FR-03. Returns draft text and nothing else.

    No send endpoint exists in this build, here or anywhere else in the app.
    The draft is returned to an editable textarea; approval is a separate,
    deliberate user action in the frontend. tests/test_draft.py asserts that
    the URL map contains no send route, so adding one becomes a visible,
    deliberate act rather than a quiet one.
    """
    body = json_body()
    email_id = required_string(body, "email_id", max_length=256)
    instruction = body.get("instruction")
    if instruction is not None and not isinstance(instruction, str):
        raise BadRequest("'instruction' must be a string if provided.")

    # FR-06. Optional and additive to the documented contract; omitting it
    # gives the neutral tone, which is what every existing caller gets.
    # Rejected rather than coerced: a typo should be a visible 400, not a
    # draft silently written in a tone nobody asked for.
    tone = body.get("tone")
    if tone is not None:
        if not isinstance(tone, str) or tone not in TONES:
            raise BadRequest(
                "'tone' must be one of: " + ", ".join(TONES) + "."
            )

    message = _load_email(email_id)

    return jsonify(
        draft_reply(
            message,
            instruction,
            config(),
            session_key=session_key(),
            user_email=current_user(),
            tone=tone or DEFAULT_TONE,
        )
    ), 200
