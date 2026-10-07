"""Header parsing (spec rule 5: deterministic data never goes through the LLM).

Sender, recipient, timestamp, subject, message ID and thread ID are all present
in the RFC-5322 headers. Asking a model to extract them would be slower, cost
money, and introduce a failure mode -- a hallucinated timestamp -- that parsing
simply does not have. So every field on the Email object below is parsed here,
and the model is only ever asked for `category` and `category_confidence`.

This module deals in headers and MIME structure only. It does not clean body
text; that is the orchestrator's preprocessing step (section 4.2), which runs
per request and never writes anything down.

ATTACHMENTS
-----------
Attachment content never reaches the body, a summary, an API response, a model
or a log. What the app keeps is what a mail client shows before you open
anything -- each attachment's file name, type and size -- so the inbox can say
"this email has a PDF" without the PDF going anywhere. (For a source that
delivers whole messages, the parser decodes an attachment only to count its
bytes, then lets them go with the request.) Every source produces that list
through attachment_of() below, so the rule for what counts as an attachment
lives in one place.
"""

import datetime as _dt
import email.utils
import hashlib
import re
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message

_ANGLE = re.compile(r"^<|>$")
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9._@-]")

# A sender chooses attachment names, so they are bounded rather than trusted:
# no path, no control characters, and a length that cannot wreck a layout.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_FILENAME = 120
# A message with more attachments than this is pathological, and listing them
# all would make one email dominate the inbox payload.
MAX_ATTACHMENTS = 50


@dataclass(frozen=True)
class Attachment:
    """Name, type and size of one attachment. Never its content.

    `size` is in bytes after transfer decoding (what the file would occupy on
    disk), or None when the source did not report it.
    """

    filename: str
    content_type: str
    size: int | None

    def as_dict(self):
        return {"filename": self.filename, "content_type": self.content_type,
                "size": self.size}


@dataclass
class SourceEmail:
    """One message as it came off the source, before any LLM involvement.

    `body_text` and `body_html` are held in memory for the life of the request
    and are never written to a store or a log (NFR-03). `attachments` describes
    attachments without containing them.
    """

    id: str
    thread_id: str
    sender: str
    sender_name: str
    recipient: str
    subject: str
    received_at: str
    unread: bool
    body_text: str = ""
    body_html: str = ""
    headers: dict = field(default_factory=dict)
    attachments: list = field(default_factory=list)

    @property
    def is_html(self):
        """True when the only content the source gave us is HTML."""
        return not self.body_text.strip() and bool(self.body_html.strip())

    @property
    def raw_body(self):
        """The body to preprocess: prefer text/plain, fall back to text/html."""
        return self.body_text if self.body_text.strip() else self.body_html


def _decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        # A malformed encoded-word must not take down the whole inbox.
        return str(value).strip()


def _message_id(message, fallback_seed):
    raw = _decode(message.get("Message-ID", ""))
    raw = _ANGLE.sub("", raw).strip()
    if not raw:
        # No Message-ID is legal but rare. Derive a stable id from the headers
        # so the same message keeps the same id across fetches -- summaries are
        # cached against this key, so it must not be random.
        raw = hashlib.sha256(fallback_seed.encode("utf-8", "replace")).hexdigest()[:24]
    return _UNSAFE_ID.sub("_", raw)


def _thread_id(message, message_id):
    """The root of the reply chain, per RFC 5322 threading.

    References holds the chain oldest-first, so its first entry is the root.
    In-Reply-To is the fallback for clients that omit References. A message
    that starts a thread is its own root.
    """
    references = _decode(message.get("References", ""))
    if references:
        first = references.split()[0]
        return _UNSAFE_ID.sub("_", _ANGLE.sub("", first))
    in_reply_to = _decode(message.get("In-Reply-To", "")).strip()
    if in_reply_to:
        return _UNSAFE_ID.sub("_", _ANGLE.sub("", in_reply_to))
    return message_id


def _received_at(message):
    """ISO-8601 timestamp from the Date header, UTC-normalised."""
    raw = message.get("Date")
    if raw:
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_dt.timezone.utc)
                return parsed.astimezone(_dt.timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    # An unparseable Date is reported as empty rather than guessed. A wrong
    # timestamp is worse than a missing one.
    return ""


def _unread(message):
    """Read state.

    IMAP carries read state as a per-mailbox flag rather than as a header.
    The fixture source stands that in as X-Unread; a real adapter maps the
    IMAP flag onto this same field.
    """
    raw = (message.get("X-Unread") or "").strip().lower()
    return raw in ("1", "true", "yes")


def _decode_payload(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _body_parts(message):
    """The leaf parts that make up the message's own body, in document order.

    An attachment is skipped together with everything inside it. Walking with
    message.walk() and checking each part on its own descended into an
    attached email (message/rfc822) and read its text as this message's body:
    the content of an attachment, summarised and sent to a model. Iterative,
    so a deeply nested message cannot exhaust the recursion limit.
    """
    stack = [message]
    while stack:
        part = stack.pop()
        if part.get_content_type() == "message/rfc822":
            continue
        if "attachment" in (part.get("Content-Disposition") or "").lower():
            continue
        if part.is_multipart():
            stack.extend(reversed(part.get_payload()))
            continue
        yield part


def _bodies(message):
    """Return (text, html), walking multipart containers.

    Attachments are skipped outright: their content is never read, never
    summarised, and never leaves the source.
    """
    text_parts, html_parts = [], []
    for part in _body_parts(message):
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            text_parts.append(_decode_payload(part))
        elif content_type == "text/html":
            html_parts.append(_decode_payload(part))
    return "\n".join(text_parts), "\n".join(html_parts)


def _clean_filename(name):
    """A display name for an attachment, safe to show and bounded in length."""
    name = _decode(name or "")
    # Some clients send the sender's local path ("C:\\Users\\ada\\report.pdf").
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip()
    if len(name) > _MAX_FILENAME:
        stem, dot, extension = name.rpartition(".")
        if dot and stem and 0 < len(extension) <= 10:
            name = name[: _MAX_FILENAME - len(extension) - 2] + "\u2026." + extension
        else:
            name = name[: _MAX_FILENAME - 1] + "\u2026"
    return name


def attachment_of(content_type, disposition, filename, content_id, size):
    """The Attachment a leaf MIME part represents, or None if it is not one.

    The rule mirrors what a mail client lists, and is the same for every source:

    * Content-Disposition: attachment -> an attachment, whatever its type.
    * text/plain and text/html parts that _bodies() reads as the message body
      are the message, not attachments.
    * A part with a Content-ID and no attachment disposition is a resource the
      HTML embeds (a signature logo, a banner) -> not listed, as clients do.
    * Any other part with a file name is an attachment (some mailers name a PDF
      without a Content-Disposition header, or mark it inline).
    * A forwarded message (message/rfc822) is an attachment even unnamed.
    """
    content_type = (content_type or "").strip().lower()
    disposition = (disposition or "").lower()
    if content_type.startswith("multipart/"):
        return None
    attached = "attachment" in disposition
    if not attached:
        if content_type in ("text/plain", "text/html"):
            return None
        if content_id:
            return None
        if not filename and content_type != "message/rfc822":
            return None
    return Attachment(
        filename=_clean_filename(filename),
        content_type=content_type,
        size=size if isinstance(size, int) and size >= 0 else None,
    )


def _attachments(message):
    """Attachments of a parsed MIME message, without reading their content
    into anything but a byte count.

    Unlike _bodies() this does not descend into an attached message/rfc822:
    a forwarded email is one attachment, not its parts.
    """
    found = []

    def visit(part):
        if len(found) >= MAX_ATTACHMENTS:
            return
        content_type = part.get_content_type()
        if content_type != "message/rfc822" and part.is_multipart():
            for child in part.get_payload():
                visit(child)
            return
        try:
            found_one = _leaf_attachment(part, content_type)
        except Exception:
            # A malformed part (a broken RFC 2231 name, an undecodable payload)
            # costs that one entry in the list, never the email: some sources
            # do not guard parse_message, and one bad header must not take the
            # whole inbox down with it.
            found_one = None
        if found_one is not None:
            found.append(found_one)

    visit(message)
    return found


def _leaf_attachment(part, content_type):
    if content_type == "message/rfc822":
        try:
            size = len(part.get_payload(0).as_bytes())
        except Exception:
            size = None
    else:
        payload = part.get_payload(decode=True)
        size = len(payload) if isinstance(payload, (bytes, bytearray)) else None
    return attachment_of(
        content_type,
        part.get("Content-Disposition"),
        part.get_filename(),
        part.get("Content-ID"),
        size,
    )


def message_id_of(message: Message) -> str:
    """The stable id for a message, from headers alone.

    Split out of parse_message so a source can locate one message by parsing
    only headers, without decoding every body in the mailbox to find it.
    """
    subject = _decode(message.get("Subject", ""))
    from_header = _decode(message.get("From", ""))
    seed = f"{from_header}|{subject}|{message.get('Date', '')}"
    return _message_id(message, seed)


def build_source_email(headers: Message, text: str, html: str, attachments) -> SourceEmail:
    """Assemble a SourceEmail from a message's headers and its extracted parts.

    `headers` only needs the top-level headers. parse_message passes the whole
    parsed message; a source that receives MIME structure some other way --
    the Gmail API's format=full, which leaves attachment bytes behind -- passes
    a headers-only message, so every source derives ids, threads, senders and
    timestamps through exactly the same code.
    """
    subject = _decode(headers.get("Subject", ""))
    from_header = _decode(headers.get("From", ""))
    sender_name, sender_address = email.utils.parseaddr(from_header)
    if not sender_name:
        # Fall back to the local part rather than inventing a display name.
        sender_name = sender_address.split("@")[0] if sender_address else ""

    message_id = message_id_of(headers)

    return SourceEmail(
        id=message_id,
        thread_id=_thread_id(headers, message_id),
        sender=sender_address,
        sender_name=sender_name,
        recipient=_decode(headers.get("To", "")),
        subject=subject,
        received_at=_received_at(headers),
        unread=_unread(headers),
        body_text=text,
        body_html=html,
        headers={"message_id": message_id},
        attachments=list(attachments)[:MAX_ATTACHMENTS],
    )


def parse_message(message: Message) -> SourceEmail:
    """Turn a parsed MIME message into a SourceEmail. No model involved."""
    text, html = _bodies(message)
    return build_source_email(message, text, html, _attachments(message))
