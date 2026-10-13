"""GET /api/inbox/<email_id>/attachment/<attachment_id> -- open an attachment.

The one route in this project that returns bytes rather than JSON. The user
can see that a file is attached; this is what lets them actually look at it.

WHY THIS IS THE MOST SECURITY-SENSITIVE ROUTE HERE
--------------------------------------------------
Everything it serves was chosen by whoever sent the email, and it serves it
from the application's own origin. That is the setup for stored XSS: a sender
attaches `invoice.html`, the recipient opens it, and the sender's script runs
with the recipient's session. Four things stop that, and all four matter:

1. An allowlist decides what may render inline (attachments.INLINE_SAFE_TYPES).
   Anything else is served as an opaque download. text/html is excluded, and
   so is image/svg+xml -- an SVG is a document that can carry <script>, which
   is the trap in treating it as "just an image".
2. `X-Content-Type-Options: nosniff`, so a browser cannot decide for itself
   that the bytes labelled text/plain look like HTML and execute them.
3. `Content-Disposition: attachment` for everything not on the allowlist, so
   the browser saves the file instead of rendering it.
4. A restrictive `Content-Security-Policy` on the response: no scripts, no
   plugins, nothing fetched from anywhere. Belt and braces for the types that
   ARE rendered inline.

AUTHENTICATION
--------------
This route is behind the same fail-closed JWT guard as everything else under
/api. That has one consequence worth stating, because it shapes the frontend:
a browser will not attach an Authorization header to <img src> or <a href>, so
the UI cannot link to this URL directly. It fetches the bytes through the API
client and renders a blob: URL instead (components/AttachmentList.jsx). The
token therefore never appears in a URL, a referrer or a browser history entry.

NFR-03
------
Nothing is cached and nothing is written to disk. The message is re-read from
the mailbox on each request, the bytes live for the life of the response, and
the filename is the only part of the attachment that is ever logged -- and it
is not: logs carry the id and the byte count.
"""

import logging
from urllib.parse import quote

from flask import Blueprint, Response

from backend.adapters.email_source import get_email_source
from backend.orchestrator.attachments import (
    INLINE_SAFE_TYPES,
    AttachmentNotFound,
    find,
)
from backend.routes.support import (
    EmailNotFound,
    config,
    current_user,
    handle_errors,
)

log = logging.getLogger(__name__)

bp = Blueprint("attachment", __name__, url_prefix="/api")

# Served for anything not on the inline allowlist. Deliberately the vaguest
# type there is: it tells the browser "bytes, no opinion", which is what makes
# it save the file rather than try to run it.
OPAQUE_TYPE = "application/octet-stream"

# No script, no plugins, no network, no framing by anyone else. Applies to the
# attachment response itself, so even a rendered PDF or text file is inert.
ATTACHMENT_CSP = (
    "default-src 'none'; img-src 'self' data:; object-src 'none'; "
    "script-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; "
    "base-uri 'none'; form-action 'none'; sandbox"
)


def _content_disposition(filename, inline):
    """A Content-Disposition a browser will accept for any filename.

    Two forms, per RFC 6266. The bare `filename=` is ASCII-only with quotes
    and backslashes stripped, because a filename containing a quote would
    otherwise terminate the header value early and let the sender inject a
    second header parameter. `filename*=` carries the real UTF-8 name for
    clients that understand it, which is all of them that matter.
    """
    ascii_name = "".join(
        ch for ch in filename if 32 <= ord(ch) < 127 and ch not in '"\\;'
    ).strip() or "attachment"
    disposition = "inline" if inline else "attachment"
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


@bp.get("/inbox/<path:email_id>/attachment/<attachment_id>")
@handle_errors
def open_attachment(email_id, attachment_id):
    """Return one attachment's bytes, for viewing or saving."""
    settings = config()
    message = get_email_source(settings, current_user()).get_email(email_id)
    if message is None:
        raise EmailNotFound(f"No email with id {email_id}.")

    attachment = find(message, attachment_id)
    if attachment is None:
        raise AttachmentNotFound("No attachment with that id on this email.")
    if attachment.too_large or not attachment.data:
        # The row in the UI already says so; this is the direct-request path.
        raise AttachmentNotFound("This attachment is not available to open.")

    declared = (attachment.content_type or "").lower().split(";")[0].strip()
    inline = declared in INLINE_SAFE_TYPES

    log.info(
        "attachment %s: serving %d byte(s) as %s (%s)",
        attachment.id[:8], attachment.size_bytes,
        declared if inline else OPAQUE_TYPE,
        "inline" if inline else "download",
    )

    response = Response(
        attachment.data,
        # The declared type is echoed back ONLY for types on the allowlist.
        # Anything else becomes octet-stream: a sender does not get to choose
        # how their bytes are interpreted in someone else's browser.
        mimetype=declared if inline else OPAQUE_TYPE,
    )
    response.headers["Content-Disposition"] = _content_disposition(
        attachment.filename, inline
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = ATTACHMENT_CSP
    # Email content must not sit in a shared cache, and the browser should
    # re-ask rather than hold it (NFR-03).
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    return response
