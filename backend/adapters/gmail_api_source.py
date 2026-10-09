"""Gmail as an email source, over the Gmail API with OAuth (EMAIL_SOURCE=gmail).

The third EmailSource, and the recommended way to read a real inbox. It returns
the same SourceEmail objects as the fixture and IMAP sources, built by the same
header parser, so no route, orchestrator module or view knows which one ran.

WHY THE API RATHER THAN IMAP
----------------------------
IMAP needs an app password: full, permanent access to the whole mailbox,
sitting in plaintext in backend/.env. This source holds an OAuth token instead,
granted for exactly one scope -- gmail.readonly -- and revocable from the
Google account's security page without changing any password.

That scope is the strongest version of the read-only claim this project makes.
The IMAP adapter is read-only because of how it is written. This one is
read-only because Google's authorisation server refuses anything else: a token
granted gmail.readonly cannot modify, trash, label or send, whatever the code
asks for. The code also only ever calls messages.list, messages.get,
messages.attachments.get and labels.list -- four reads -- which the tests
check.

THE COSTS, STATED
-----------------
* A Google Cloud project, the Gmail API enabled on it, and an OAuth consent
  screen -- a one-off setup, documented in the README.
* While the consent screen is in "Testing", Google expires the refresh token
  after 7 days. The app then says so in the inbox, and
  `python -m backend.scripts.gmail_auth` reconnects in under a minute.
* gmail.readonly is a *restricted* scope, so publishing the app for other users
  needs Google verification and a third-party security assessment. Fine for a
  project account in Testing; not a route to production at this scale.

NFR-03
------
Messages are fetched per request and held for the life of that request. The
only thing written to disk is the OAuth token, which is a credential, not mail.
No body is logged; logs carry counts and Gmail message ids only.

WHAT IS DOWNLOADED
------------------
Messages are fetched with format=full: Gmail returns the headers and the body
parts, and leaves every attachment behind as an id and a size. The app lists
attachments by name, type and size (headers.attachment_of), and loading the
inbox or a message never fetches their content, so a 10 MB PDF costs the inbox
a few bytes of metadata rather than ten megabytes on every load. format=raw,
which carries every attachment inline, is used only for a message whose body
text Gmail also left out of line -- that one message is fetched whole, so its
text is never lost.

One attachment is downloaded when a person opens it, and only then:
get_attachment() fetches that single part by its id (messages.attachments.get)
for the route that serves it, and nothing keeps the bytes after the response.
"""

import base64
import json
import logging
import os
import re
import threading
from email import policy
from email.message import Message
from email.parser import BytesParser, Parser

from backend.adapters.email_source import EmailSource, EmailSourceError
from backend.adapters.headers import (
    MAX_ATTACHMENTS,
    AttachmentContent,
    attachment_content,
    attachment_of,
    build_source_email,
    message_id_of,
    parse_message,
)

log = logging.getLogger(__name__)

# The ONLY scope this app ever requests. tests/test_gmail_api_source.py pins it,
# so widening it has to be a deliberate, visible change.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Labels whose id is also their name. Anything else is a user label, whose id
# ("Label_123") has to be looked up from its display name.
_SYSTEM_LABELS = {
    "INBOX", "SPAM", "TRASH", "UNREAD", "STARRED", "IMPORTANT", "SENT", "DRAFT",
    "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES", "CATEGORY_FORUMS",
}

# Gmail recommends keeping batches at or under 50 calls.
_BATCH_SIZE = 50

# Headers needed to compute our message id without downloading the body.
_ID_HEADERS = ["Message-ID", "From", "Subject", "Date"]

# RFC 5322 field names: printable ASCII except the colon. Anything else from
# the API is dropped rather than allowed to bend the header block below.
# Used with fullmatch: "$" alone also matches before a trailing newline, and a
# name ending "\n" would break the header block it is written into.
_FIELD_NAME = re.compile(r"[!-9;-~]+")

_RECONNECT = "Reconnect with:  python -m backend.scripts.gmail_auth"


class _BodyNotInline(Exception):
    """format=full left a body part's text out of line (an attachmentId, no data)."""


# --- credentials ---------------------------------------------------------------


class _Credentials:
    """Loads the saved OAuth token, refreshes it, and writes refreshes back.

    Shared across requests, with a lock, because the Flask dev server is
    threaded and two requests refreshing at once would each spend a refresh and
    race to write the file. The Credentials object is safe to share; the HTTP
    transport is not, which is why a fresh one is built per call below.
    """

    def __init__(self, token_path):
        self.token_path = token_path
        self._creds = None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._creds is None:
                self._creds = self._load()
            if not self._creds.valid:
                self._refresh()
            return self._creds

    def _load(self):
        from google.oauth2.credentials import Credentials

        if not os.path.exists(self.token_path):
            raise EmailSourceError(
                "Gmail is not connected yet. " + _RECONNECT
            )
        try:
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise EmailSourceError(
                f"The saved Gmail token at {self.token_path} is unreadable. " + _RECONNECT
            ) from exc

        # A token granted a different scope would fail on the first call with
        # an opaque 403. Say what is wrong before that happens.
        granted = set(creds.scopes or [])
        if granted and not set(SCOPES) <= granted:
            raise EmailSourceError(
                "The saved Gmail token was not granted read access. " + _RECONNECT
            )
        return creds

    def _refresh(self):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request

        if not self._creds.refresh_token:
            raise EmailSourceError(
                "The saved Gmail token cannot be renewed. " + _RECONNECT
            )
        try:
            self._creds.refresh(Request())
        except RefreshError as exc:
            # invalid_grant: expired or revoked. The 7-day Testing expiry lands
            # here, and it is the error most likely to appear on a demo day, so
            # it says exactly that rather than "authentication failed".
            self._creds = None
            raise EmailSourceError(
                "Gmail access has expired or was revoked. While the Google app "
                "is in Testing, Google ends access every 7 days. " + _RECONNECT
            ) from exc
        except OSError as exc:
            raise EmailSourceError("Could not reach Google to renew Gmail access.") from exc
        self._save()

    def _save(self):
        # Atomic, and owner-readable only where the OS supports it: this file
        # is a live credential for someone's mailbox.
        temp = self.token_path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(self._creds.to_json())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.token_path)


# --- source ------------------------------------------------------------------


class GmailApiSource(EmailSource):
    """Reads the newest `limit` messages under one Gmail label."""

    def __init__(self, token_path, label="INBOX", limit=25, timeout=20, service=None):
        self.label = (label or "INBOX").strip()
        self.limit = max(1, min(int(limit), 500))
        self.timeout = timeout
        self._credentials = _Credentials(token_path)
        # Tests inject a fake service; nothing else should.
        self._injected = service
        self._label_id = None

    # --- plumbing ------------------------------------------------------------

    def _service(self):
        """A service object for one call.

        httplib2 is not thread-safe, so the service (which owns a connection)
        is not shared between requests. Building one is cheap: the discovery
        document ships with the library, so no network call is made here.
        """
        if self._injected is not None:
            return self._injected

        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build

        creds = self._credentials.get()
        http = AuthorizedHttp(creds, http=httplib2.Http(timeout=self.timeout))
        return build("gmail", "v1", http=http, cache_discovery=False, static_discovery=True)

    def _call(self, what, fn):
        """Run one API call, turning every failure into an EmailSourceError."""
        from googleapiclient.errors import HttpError

        try:
            return fn()
        except EmailSourceError:
            raise
        except HttpError as exc:
            raise _explain_http_error(exc, what, self.label) from exc
        except Exception as exc:
            # httplib2 raises its own error types, socket timeouts surface as
            # OSError, and the transport can raise from deep inside a refresh.
            # All of them mean "Gmail could not be reached" to the person
            # looking at an empty inbox. Type name only: never the message.
            log.warning("gmail api: %s failed (%s)", what, type(exc).__name__)
            raise EmailSourceError(
                "Could not reach Gmail. Check the network connection and try again."
            ) from exc

    def _resolve_label(self, service):
        if self._label_id:
            return self._label_id
        if self.label.upper() in _SYSTEM_LABELS:
            self._label_id = self.label.upper()
            return self._label_id

        response = self._call(
            "list labels", service.users().labels().list(userId="me").execute
        )
        wanted = self.label.lower()
        for label in response.get("labels", []):
            if label.get("id") == self.label or (label.get("name") or "").lower() == wanted:
                self._label_id = label["id"]
                return self._label_id
        raise EmailSourceError(
            f"Gmail has no label called {self.label!r}. Set GMAIL_MAILBOX to a label "
            f"that exists, for example INBOX."
        )

    def _list_ids(self, service, query=None, limit=None):
        kwargs = {
            "userId": "me",
            "labelIds": [self._resolve_label(service)],
            "maxResults": limit or self.limit,
        }
        if query:
            kwargs["q"] = query
        response = self._call(
            "list messages", service.users().messages().list(**kwargs).execute
        )
        return [m["id"] for m in response.get("messages", []) if m.get("id")]

    def _batch_get(self, service, ids, fmt):
        """Fetch several messages in as few HTTP round trips as possible.

        One bad message is skipped, not fatal: a single malformed or deleted
        message must not empty the whole inbox. But if EVERY fetch failed, the
        problem is the connection, not the messages, and an empty inbox would
        hide it -- so that case raises.
        """
        results, errors = {}, {}

        def collect(request_id, response, exception):
            if exception is not None:
                errors[request_id] = exception
            else:
                results[request_id] = response

        for start in range(0, len(ids), _BATCH_SIZE):
            batch = service.new_batch_http_request(callback=collect)
            for gid in ids[start:start + _BATCH_SIZE]:
                kwargs = {"userId": "me", "id": gid, "format": fmt}
                if fmt == "metadata":
                    kwargs["metadataHeaders"] = _ID_HEADERS
                batch.add(service.users().messages().get(**kwargs), request_id=gid)
            self._call("fetch messages", batch.execute)

        if ids and not results and errors:
            # Re-raised through _call so it gets the same translation as any
            # other API failure. _call always raises here.
            self._call("fetch messages", _raiser(next(iter(errors.values()))))
        for gid, exc in errors.items():
            log.warning("gmail api: skipping message %s (%s)", gid, type(exc).__name__)
        return results

    # --- conversion ----------------------------------------------------------

    @staticmethod
    def _to_source_email(response):
        """A SourceEmail from either a format=full or a format=raw response.

        Raises _BodyNotInline when a full response left body text out of line;
        the caller then fetches that message as raw instead.
        """
        if response.get("raw"):
            return GmailApiSource._from_raw(response)
        if response.get("payload"):
            return GmailApiSource._from_full(response)
        raise ValueError("message has no body")

    @staticmethod
    def _from_raw(response):
        raw = response["raw"]
        data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        message = BytesParser(policy=policy.default).parsebytes(data)

        # A headerless message would hash to the same id as every other
        # headerless message, and so share one summary cache entry. Refuse it
        # rather than show two different emails the same summary.
        if not any(message.get(name) for name in _ID_HEADERS):
            raise ValueError("message has no usable headers")

        # Read state comes from Gmail's UNREAD label, never from the message.
        # X-Unread is the fixture source's stand-in (see headers.py), and a
        # sender could otherwise set it and decide how their own mail appears.
        del message["X-Unread"]
        message["X-Unread"] = "1" if "UNREAD" in (response.get("labelIds") or []) else "0"
        return parse_message(message)

    @staticmethod
    def _from_full(response):
        """Build the SourceEmail from Gmail's parsed MIME tree.

        Body text is read exactly as headers._bodies() reads a raw message:
        multipart containers skipped, attachment-disposition parts skipped,
        text/plain and text/html parts decoded with their own charset and
        joined. Headers, ids, threads and timestamps go through the shared
        headers.build_source_email(), so a message gets the same id here as it
        would from format=raw and from the metadata lookup in get_email().
        """
        payload = response.get("payload") or {}
        headers = _headers_message(payload.get("headers"))
        if not any(headers.get(name) for name in _ID_HEADERS):
            raise ValueError("message has no usable headers")
        # As in _from_raw: read state is Gmail's label, never a header.
        del headers["X-Unread"]
        headers["X-Unread"] = "1" if "UNREAD" in (response.get("labelIds") or []) else "0"

        text_parts, html_parts = [], []
        for part in _body_parts(payload):
            mime = (part.get("mimeType") or "").lower()
            if mime.startswith("multipart/"):
                continue
            part_headers = _part_headers(part)
            if mime == "text/plain":
                text_parts.append(_part_text(part, part_headers))
            elif mime == "text/html":
                html_parts.append(_part_text(part, part_headers))

        return build_source_email(
            headers, "\n".join(text_parts), "\n".join(html_parts), _full_attachments(payload)
        )

    @staticmethod
    def _id_from_metadata(response):
        """Our message id, computed from headers alone, no body downloaded."""
        headers = (response.get("payload") or {}).get("headers") or []
        return message_id_of(_headers_message(headers, names=_ID_HEADERS))

    # --- EmailSource ---------------------------------------------------------

    def list_emails(self):
        service = self._service()
        ids = self._list_ids(service)
        fetched = self._batch_get(service, ids, "full")

        emails, out_of_line = [], []
        for gid in ids:
            response = fetched.get(gid)
            if response is None:
                continue
            try:
                emails.append(self._to_source_email(response))
            except _BodyNotInline:
                out_of_line.append(gid)
            except Exception as exc:
                log.warning("gmail api: skipping unparseable message %s (%s)",
                            gid, type(exc).__name__)

        if out_of_line:
            # Rare: Gmail kept some body text out of line. Fetch just those
            # messages whole rather than show them without their text.
            log.info("gmail api: %d message(s) keep body text out of line; "
                     "fetching those whole", len(out_of_line))
            whole = self._batch_get(service, out_of_line, "raw")
            for gid in out_of_line:
                response = whole.get(gid)
                if response is None:
                    continue
                try:
                    emails.append(self._to_source_email(response))
                except Exception as exc:
                    log.warning("gmail api: skipping unparseable message %s (%s)",
                                gid, type(exc).__name__)

        emails.sort(key=lambda e: e.received_at or "", reverse=True)
        log.info("gmail api: fetched %d message(s) from %s", len(emails), self.label)
        return emails

    def _locate(self, service, email_id):
        """Gmail's id for the message with our id, or None.

        Fast path: Gmail can search by Message-ID. It is not sufficient on its
        own, because our ids are sanitised -- characters outside [A-Za-z0-9._@-]
        become underscores, and Gmail-generated Message-IDs routinely contain
        '+' and '='. So every candidate is verified by recomputing its id, and
        on a miss the recent messages are scanned by headers alone.
        """
        candidates = self._list_ids(service, query=f"rfc822msgid:{email_id}", limit=5)
        match = self._first_matching(service, candidates, email_id)
        if match is None:
            match = self._first_matching(service, self._list_ids(service), email_id)
        return match

    def get_email(self, email_id):
        """Locate one message by our id, downloading at most one body."""
        service = self._service()

        match = self._locate(service, email_id)
        if match is None:
            return None

        full = self._batch_get(service, [match], "full").get(match)
        if full is None:
            # Present a moment ago and gone now: deleted or moved in between.
            return None
        try:
            return self._to_source_email(full)
        except _BodyNotInline:
            whole = self._batch_get(service, [match], "raw").get(match)
            return None if whole is None else self._to_source_email(whole)

    def get_attachment(self, email_id, index):
        """The bytes of one listed attachment, fetched when a person opens it.

        The message is fetched the way the inbox fetches it (format=full, which
        carries no attachment bytes) and walked exactly as its list was built,
        so `index` names the same part here as it did on screen. Only that one
        part is then downloaded, by its id.
        """
        service = self._service()

        match = self._locate(service, email_id)
        if match is None:
            return None
        full = self._batch_get(service, [match], "full").get(match)
        if full is None:
            return None
        try:
            self._to_source_email(full)
        except _BodyNotInline:
            # get_email() listed this message from format=raw, so its
            # attachments are read from that same parse.
            return self._attachment_from_raw(service, match, index)

        parts = _full_attachment_parts(full.get("payload") or {})
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(parts):
            return None
        part, attachment = parts[index]
        body = part.get("body") or {}
        try:
            if body.get("data"):
                data = _unb64(body["data"])
            elif body.get("attachmentId"):
                response = self._call(
                    "fetch the attachment",
                    service.users().messages().attachments().get(
                        userId="me", messageId=match, id=body["attachmentId"]).execute,
                )
                data = _unb64((response or {}).get("data") or "")
            else:
                # Gmail gave this part nothing to fetch it by (an empty file,
                # or an attached email it describes by its parts instead). The
                # whole message has it; the name and type are checked so a
                # difference between the two parses can never serve another
                # attachment in its place.
                found = self._attachment_from_raw(service, match, index)
                if found is None or (found.filename, found.content_type) != (
                        attachment.filename, attachment.content_type):
                    return None
                return found
        except ValueError:
            # Not base64 after all. Ids only: never the name or the content.
            log.warning("gmail api: attachment %d of message %s is undecodable", index, match)
            return None
        return AttachmentContent(
            filename=attachment.filename, content_type=attachment.content_type, data=data)

    def _attachment_from_raw(self, service, gid, index):
        """One attachment read out of the whole message (format=raw)."""
        whole = self._batch_get(service, [gid], "raw").get(gid)
        if whole is None or not whole.get("raw"):
            return None
        message = BytesParser(policy=policy.default).parsebytes(_unb64(whole["raw"]))
        return attachment_content(message, index)

    def _first_matching(self, service, ids, email_id):
        if not ids:
            return None
        metadata = self._batch_get(service, ids, "metadata")
        for gid in ids:
            response = metadata.get(gid)
            if response is not None and self._id_from_metadata(response) == email_id:
                return gid
        return None


def _raiser(exc):
    def _raise():
        raise exc
    return _raise


# --- Gmail MIME tree helpers ---------------------------------------------------


def _headers_message(headers, names=None):
    """A headers-only Message from Gmail's [{name, value}] list.

    Shared by the metadata id lookup and the format=full conversion, so the two
    always compute the same id for a message. Values are parsed as text rather
    than bytes: if Gmail hands back a value it has already decoded to Unicode,
    it stays Unicode instead of turning into surrogate escapes. Names are
    matched without regard to case, because a message may carry "Message-Id"
    where we ask for "Message-ID".
    """
    wanted = {n.lower() for n in names} if names is not None else None
    lines = []
    for header in headers or []:
        name, value = header.get("name"), header.get("value")
        if not name or value is None or not _FIELD_NAME.fullmatch(name):
            continue
        if wanted is not None and name.lower() not in wanted:
            continue
        # Newlines in a value would let one header inject another.
        safe = str(value).replace("\r", " ").replace("\n", " ")
        lines.append(f"{name}: {safe}")
    block = "\r\n".join(lines) + "\r\n\r\n"
    return Parser(policy=policy.default).parsestr(block, headersonly=True)


def _body_parts(payload):
    """The leaf parts of a format=full tree that belong to this message's own
    body, in document order, as headers._body_parts() does for a raw message.

    An attachment is skipped together with everything inside it. Gmail parses
    an attached email (message/rfc822) into child parts of its own, and a walk
    that checked each part alone read that email's text as this one's body.
    """
    stack = [payload]
    while stack:
        part = stack.pop()
        if (part.get("mimeType") or "").lower() == "message/rfc822":
            continue
        if "attachment" in _part_headers(part).get("content-disposition", "").lower():
            continue
        children = part.get("parts") or []
        if children:
            stack.extend(reversed(children))
            continue
        yield part


def _part_headers(part):
    """The first value of each header on one part, keyed by lower-case name."""
    found = {}
    for header in part.get("headers") or []:
        name = (header.get("name") or "").lower()
        if name and name not in found and header.get("value") is not None:
            found[name] = str(header["value"])
    return found


def _probe(part_headers):
    """A bare Message carrying a part's type headers, for the stdlib's parsing
    of charset and file-name parameters (RFC 2231 included)."""
    probe = Message()
    for name, key in (("Content-Type", "content-type"),
                      ("Content-Disposition", "content-disposition")):
        if part_headers.get(key):
            probe[name] = part_headers[key].replace("\r", " ").replace("\n", " ")
    return probe


def _part_text(part, part_headers):
    """Decode one inline text part, as headers._decode_payload() does."""
    body = part.get("body") or {}
    data = body.get("data")
    if not data:
        if body.get("attachmentId"):
            raise _BodyNotInline()
        return ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    charset = _probe(part_headers).get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _unb64(data):
    """Decode Gmail's unpadded URL-safe base64."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _full_attachment_parts(payload):
    """(part, Attachment) for each attachment in a format=full tree, in the
    order they are listed: name, type and Gmail's size, never data.

    The one walk behind both the list and get_attachment(), so an index names
    the same part to both. Like headers._attachment_parts(), an attached
    message/rfc822 counts once and is not descended into.
    """
    found = []

    def visit(part):
        if len(found) >= MAX_ATTACHMENTS:
            return
        mime = (part.get("mimeType") or "").lower()
        if mime != "message/rfc822" and part.get("parts"):
            for child in part["parts"]:
                visit(child)
            return
        try:
            part_headers = _part_headers(part)
            filename = part.get("filename") or _probe(part_headers).get_filename()
            attachment = attachment_of(
                mime,
                part_headers.get("content-disposition"),
                filename,
                part_headers.get("content-id"),
                (part.get("body") or {}).get("size"),
            )
        except Exception:
            # As in headers._attachment_parts: a malformed part costs its own
            # entry, never the email.
            attachment = None
        if attachment is not None:
            found.append((part, attachment))

    visit(payload)
    return found


def _full_attachments(payload):
    """Attachments in a format=full tree: name, type and Gmail's size, never data."""
    return [attachment for _part, attachment in _full_attachment_parts(payload)]


def _explain_http_error(exc, what, label):
    """A sentence a person can act on. Status and reason only are logged."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    reason = _reason(exc)
    log.warning("gmail api: %s -> HTTP %s (%s)", what, status, reason or "no reason")

    if status == 401:
        return EmailSourceError("Gmail rejected the saved sign-in. " + _RECONNECT)
    if status == 403:
        if reason in ("accessNotConfigured", "SERVICE_DISABLED"):
            return EmailSourceError(
                "The Gmail API is not enabled on the Google Cloud project. Enable it "
                "under APIs & Services > Library > Gmail API, then try again."
            )
        if reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"):
            return EmailSourceError(
                "The saved Gmail token does not have read access. " + _RECONNECT
            )
        if reason in ("rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"):
            return EmailSourceError("Gmail is rate limiting this app. Wait a minute and reload.")
        return EmailSourceError(f"Gmail refused to {what}. " + _RECONNECT)
    if status == 404:
        return EmailSourceError(
            f"Gmail could not find {label!r}. Set GMAIL_MAILBOX to a label that exists."
        )
    if status == 429:
        return EmailSourceError("Gmail is rate limiting this app. Wait a minute and reload.")
    if status is not None and status >= 500:
        return EmailSourceError("Gmail is having trouble right now. Try again shortly.")
    return EmailSourceError(f"Gmail could not {what}.")


def _reason(exc):
    """The machine-readable reason from a Google API error body, if any."""
    content = getattr(exc, "content", b"") or b""
    try:
        body = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    for item in error.get("errors") or []:
        if isinstance(item, dict) and item.get("reason"):
            return item["reason"]
    for item in error.get("details") or []:
        if isinstance(item, dict) and item.get("reason"):
            return item["reason"]
    return error.get("status")
