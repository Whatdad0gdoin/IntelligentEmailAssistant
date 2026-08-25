"""Header parsing (spec rule 5: deterministic data never goes through the LLM).

Sender, recipient, timestamp, subject, message ID and thread ID are all present
in the RFC-5322 headers. Asking a model to extract them would be slower, cost
money, and introduce a failure mode -- a hallucinated timestamp -- that parsing
simply does not have. So every field on the Email object below is parsed here,
and the model is only ever asked for `category` and `category_confidence`.

This module deals in headers and MIME structure only. It does not clean body
text; that is the orchestrator's preprocessing step (section 4.2), which runs
per request and never writes anything down.
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


@dataclass
class SourceEmail:
    """One message as it came off the source, before any LLM involvement.

    `body_text` and `body_html` are held in memory for the life of the request
    and are never written to a store or a log (NFR-03).
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


def _bodies(message):
    """Return (text, html), walking multipart containers.

    Attachments are skipped outright: their content is never read, never
    summarised, and never leaves the source.
    """
    text_parts, html_parts = [], []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            text_parts.append(_decode_payload(part))
        elif content_type == "text/html":
            html_parts.append(_decode_payload(part))
    return "\n".join(text_parts), "\n".join(html_parts)


def parse_message(message: Message) -> SourceEmail:
    """Turn a parsed MIME message into a SourceEmail. No model involved."""
    subject = _decode(message.get("Subject", ""))
    from_header = _decode(message.get("From", ""))
    sender_name, sender_address = email.utils.parseaddr(from_header)
    if not sender_name:
        # Fall back to the local part rather than inventing a display name.
        sender_name = sender_address.split("@")[0] if sender_address else ""

    seed = f"{from_header}|{subject}|{message.get('Date', '')}"
    message_id = _message_id(message, seed)
    text, html = _bodies(message)

    return SourceEmail(
        id=message_id,
        thread_id=_thread_id(message, message_id),
        sender=sender_address,
        sender_name=sender_name,
        recipient=_decode(message.get("To", "")),
        subject=subject,
        received_at=_received_at(message),
        unread=_unread(message),
        body_text=text,
        body_html=html,
        headers={"message_id": message_id},
    )
