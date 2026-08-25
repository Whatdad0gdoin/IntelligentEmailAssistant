"""GET /api/inbox (FR-08, spec section 3).

Returns the mailbox already grouped into the five buckets. The user does no
sorting: that is the point of FR-08, so the grouping is done here and the
frontend renders what it is given.

Every field on an Email except `category` and `category_confidence` is parsed
from headers by the adapter (rule 5). The model sees the body and the subject
and returns a label; it is never asked who sent the message or when.

Classification runs as one batch for the whole inbox on this call -- one round
trip on login, not one per email as the list renders (section 3, NFR-01).
Results are cached per email id, so a re-fetch costs no API calls.
"""

from flask import Blueprint, jsonify

from backend.adapters.email_source import get_email_source
from backend.orchestrator.classify import classify_emails
from backend.orchestrator.preprocess import preprocess, snippet
from backend.orchestrator.schemas import CATEGORIES, REVIEW_CATEGORY
from backend.routes.support import config, current_user, handle_errors, session_key

bp = Blueprint("inbox", __name__, url_prefix="/api")

# Fixed order so the UI renders the same layout every time. Every key is always
# present, empty or not -- a missing key would make the frontend branch on
# absence, and an empty group is information ("nothing needs review").
GROUP_ORDER = list(CATEGORIES) + [REVIEW_CATEGORY]


@bp.get("/inbox")
@handle_errors
def inbox():
    settings = config()
    user = current_user()

    messages = get_email_source(settings).list_emails()

    labels = {
        result["id"]: result
        for result in classify_emails(
            [
                {"id": m.id, "subject": m.subject, "body": m.raw_body}
                for m in messages
            ],
            settings,
            session_key=session_key(),
            user=user,
        )
    }

    groups = {name: [] for name in GROUP_ORDER}
    for message in messages:
        label = labels.get(message.id) or {}
        category = label.get("category", REVIEW_CATEGORY)
        # A category outside the five would silently vanish from the response,
        # so anything unexpected lands in Review where it stays visible.
        if category not in groups:
            category = REVIEW_CATEGORY

        # The preview is cut from the cleaned body, so the list does not show a
        # quoted reply chain or an unsubscribe footer as the "content".
        cleaned = preprocess(
            message.raw_body,
            settings.token_budget_chars,
            is_html=message.is_html,
            label=f"snippet {message.id[:12]}",
        )

        groups[category].append({
            "id": message.id,
            "thread_id": message.thread_id,
            "sender": message.sender,
            "sender_name": message.sender_name,
            "subject": message.subject,
            "received_at": message.received_at,
            "unread": message.unread,
            "snippet": snippet(cleaned.text, settings.snippet_chars),
            "category": category,
            "category_confidence": label.get("confidence", 0.0),
        })

    return jsonify({"groups": groups}), 200
