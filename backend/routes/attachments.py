"""GET /api/inbox/<email_id>/attachments/<index> -- open one attachment.

The inbox says a file is attached; this is what lets the signed-in person look
at it. It is the only route that returns bytes rather than JSON, and the only
place attachment content leaves the mail source (see adapters/headers.py).
`index` is the attachment's position in the `attachments` list the inbox and
the reading pane already return, so no new identifier is invented.

WHAT STAYS TRUE
---------------
Nothing here reaches a model, a summary or a log, and nothing is cached or
written to disk (NFR-03). The message is read from the mailbox again on every
request, one attachment is decoded, and its bytes go with the response -- the
position an email body has always had on GET /api/inbox/<id>. Log lines carry
the index, a byte count and the type served, never a file name.

WHY THE HEADERS MATTER
----------------------
Everything served here was chosen by whoever sent the email, and it comes from
the application's own origin. A sender who attaches `invoice.html` is hoping it
will be rendered there. So:

* Only the types in INLINE_TYPES are served under their own type, to be shown
  in the page. Anything else -- text/html and image/svg+xml above all, since an
  SVG is a document that can carry script -- goes out as
  application/octet-stream with `Content-Disposition: attachment`, which a
  browser saves and does not render.
* `X-Content-Type-Options: nosniff` stops a browser deciding for itself that
  bytes labelled text/plain look like HTML.
* The Content-Security-Policy allows nothing and sandboxes the response, for a
  browser that is somehow navigated straight to this URL.
* `Cache-Control: no-store`: mail content does not belong in a browser or
  proxy cache.

AUTHENTICATION
--------------
The route sits behind the same fail-closed JWT guard as the rest of /api. A
browser will not put an Authorization header on <img src> or <a href>, so the
frontend cannot link to this URL: it fetches the bytes through the API client
and shows them from a blob: URL. The token therefore never appears in a URL.
"""

import logging
from urllib.parse import quote

from flask import Blueprint, Response

from backend.adapters.email_source import get_email_source
from backend.routes.support import (
    AttachmentNotFound,
    config,
    current_user,
    handle_errors,
)

log = logging.getLogger(__name__)

bp = Blueprint("attachments", __name__, url_prefix="/api")

# Types a browser may show in the page. A security boundary, not a convenience:
# see the module docstring before adding to it. Every entry is either a raster
# image, a PDF (shown by the browser's own viewer) or plain text.
INLINE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "application/pdf",
    "text/plain", "text/csv",
})

# What everything else is served as: bytes, with no opinion about what they are.
DOWNLOAD_TYPE = "application/octet-stream"

ATTACHMENT_CSP = "default-src 'none'; sandbox"


def _download_name(filename, content_type):
    """A file name for the browser's save dialog, when the sender gave none."""
    if filename:
        return filename
    return "forwarded-message.eml" if content_type == "message/rfc822" else "attachment"


def _content_disposition(filename, inline):
    """A Content-Disposition header that is safe for any sender-chosen name.

    Two forms, per RFC 6266. The quoted `filename=` keeps printable ASCII only,
    without quotes, backslashes or semicolons, so a name cannot end the value
    early and add a parameter of its own. `filename*=` carries the real name,
    percent-encoded, for every browser that reads it.
    """
    ascii_name = "".join(
        ch for ch in filename if 32 <= ord(ch) < 127 and ch not in '"\\;'
    ).strip() or "attachment"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@bp.get("/inbox/<path:email_id>/attachments/<int:index>")
@handle_errors
def open_attachment(email_id, index):
    """The bytes of one attachment, to show in the page or to save."""
    content = get_email_source(config(), current_user()).get_attachment(email_id, index)
    if content is None:
        raise AttachmentNotFound("That attachment could not be found on this email.")

    declared = (content.content_type or "").split(";")[0].strip().lower()
    inline = declared in INLINE_TYPES
    served = declared if inline else DOWNLOAD_TYPE

    log.info("attachment %d of %s: %d byte(s) served as %s",
             index, email_id[:12], len(content.data), served)

    response = Response(content.data, mimetype=served)
    response.headers["Content-Disposition"] = _content_disposition(
        _download_name(content.filename, declared), inline)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = ATTACHMENT_CSP
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    return response
