"""Gmail as an email source, over IMAP (section 1).

This is the second EmailSource. It reads a real Gmail mailbox and returns the
same SourceEmail objects FixtureEmailSource returns, so no route, orchestrator
module or view changes -- which is the claim email_source.py has been making
since the fixture source was the only one, now tested rather than asserted.

WHY IMAP AND NOT SMTP
---------------------
The obvious reading of "receive email from Gmail" is that Gmail delivers to
backend/mailserver.py. It cannot. Inbound delivery needs a public MX record, a
reachable port 25 and TLS on a domain you own, and the result would be an open
relay candidate sitting on a university network. Gmail is therefore *read*,
not delivered to. The local SMTP server keeps its own job -- putting a test
message into the app with no account at all -- and the two do not overlap.

WHY IMAP AND NOT THE GMAIL API
------------------------------
The Gmail API is the better production answer: OAuth, a revocable read-only
grant, no password anywhere. It also needs a Google Cloud project, a consent
screen, three dependencies and a cached token file. IMAP with an app password
is stdlib, is configured in one place, and exercises exactly the same adapter
boundary. The trade-off is real and belongs in the report: an app password is
full mailbox access in plaintext in backend/.env, which is why the setup notes
say to point this at an account created for the project.

READ-ONLY, THREE TIMES OVER
---------------------------
"The assistant never changes your mailbox" is the claim that makes pointing
this at real mail defensible, so it does not rest on one mechanism:

* the mailbox is opened with SELECT (readonly), so the server itself refuses
  any state change on the connection;
* bodies are fetched with BODY.PEEK[] rather than RFC822, which does not set
  \\Seen even on a writable connection;
* nothing anywhere in the app issues STORE, APPEND, EXPUNGE or COPY.

Opening someone's mail to summarise it and marking it read as a side effect is
a bug they would find in their own inbox rather than in this application.

NFR-03 IS UNCHANGED
-------------------
Messages are fetched per request and held for the life of that request. Nothing
is written to disk and no body is logged -- only counts and UIDs. Gmail is the
mail server here, occupying the position the fixture directory occupied.
"""

import imaplib
import logging
import re
import socket
import ssl
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser

from backend.adapters.email_source import EmailSource, EmailSourceError
from backend.adapters.headers import message_id_of, parse_message

log = logging.getLogger(__name__)

# FETCH replies arrive as (prefix, payload) tuples where the prefix carries the
# UID and the flags: b'3 (UID 12 FLAGS (\\Seen) BODY[] {2345}'.
_UID = re.compile(rb"UID\s+(\d+)")
_FLAGS = re.compile(rb"FLAGS\s+\(([^)]*)\)")

_SEEN = b"\\Seen"


def _quote_mailbox(name):
    """IMAP mailbox names are astrings; '[Gmail]/All Mail' needs the quotes."""
    if name.startswith('"') and name.endswith('"'):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def _parse_fetch(data):
    """Return [(uid, unread, raw_bytes)] from a UID FETCH response.

    imaplib hands back a flat list mixing the tuples we want with the b')'
    terminators between them, so anything that is not a two-part tuple is
    skipped rather than trusted to sit at a fixed position.
    """
    out = []
    for item in data or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        prefix, raw = item[0] or b"", item[1]
        if not raw:
            continue
        uid_match = _UID.search(prefix)
        flags_match = _FLAGS.search(prefix)
        flags = flags_match.group(1) if flags_match else b""
        uid = uid_match.group(1) if uid_match else b""
        out.append((uid, _SEEN not in flags, raw))
    return out


class GmailImapSource(EmailSource):
    """Reads the newest `limit` messages from one Gmail mailbox.

    Connections are opened per call and closed again, the same way
    FixtureEmailSource re-reads its directory per call. That costs a TLS
    handshake and a login -- roughly half a second -- on every inbox load. A
    pooled connection would save it, at the price of holding an authenticated
    IMAP session across requests and handling it going stale underneath a
    threaded server: a lot of state to own for a saving no user notices next to
    the model call happening on the same page.
    """

    def __init__(self, host, port, username, password, mailbox="INBOX",
                 limit=25, timeout=20):
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.mailbox = mailbox
        self.limit = max(1, int(limit))
        self.timeout = timeout

    # --- connection --------------------------------------------------------

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            # close() fails when no mailbox is selected and logout() fails on a
            # dropped socket. Neither is worth turning a successful fetch into
            # an error, so both are best-effort.
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass

    def _connect(self):
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        except (OSError, ssl.SSLError, socket.timeout) as exc:
            raise EmailSourceError(
                f"Could not reach {self.host}:{self.port}. Check the network "
                f"connection and that IMAP is not blocked here."
            ) from exc

        try:
            conn.login(self.username, self._password)
        except imaplib.IMAP4.error as exc:
            # The exception text is deliberately not repeated: it can echo the
            # credential back, and this message goes to a log.
            raise EmailSourceError(
                f"Gmail rejected the sign-in for {self.username}. GMAIL_APP_PASSWORD "
                f"must be a 16-character app password, generated with 2-step "
                f"verification switched on -- not the account password."
            ) from exc

        try:
            status, _ = conn.select(_quote_mailbox(self.mailbox), readonly=True)
        except imaplib.IMAP4.error as exc:
            raise EmailSourceError(f"Gmail refused to open {self.mailbox!r}.") from exc
        if status != "OK":
            raise EmailSourceError(
                f"Gmail has no mailbox called {self.mailbox!r}. Set GMAIL_MAILBOX to "
                f"a label that exists, for example INBOX."
            )
        return conn

    # --- fetching ----------------------------------------------------------

    def _recent_uids(self, conn):
        """The newest `limit` UIDs. SEARCH returns them ascending, so tail."""
        try:
            status, data = conn.uid("SEARCH", None, "ALL")
        except imaplib.IMAP4.error as exc:
            raise EmailSourceError("Gmail refused the mailbox search.") from exc
        if status != "OK":
            raise EmailSourceError("Gmail refused the mailbox search.")
        uids = (data[0] if data else b"") or b""
        return uids.split()[-self.limit:]

    def _fetch(self, conn, uids, headers_only):
        if not uids:
            return []
        what = "(FLAGS BODY.PEEK[HEADER])" if headers_only else "(FLAGS BODY.PEEK[])"
        try:
            status, data = conn.uid("FETCH", b",".join(uids), what)
        except imaplib.IMAP4.error as exc:
            raise EmailSourceError("Gmail refused the message fetch.") from exc
        if status != "OK":
            raise EmailSourceError("Gmail refused the message fetch.")
        return _parse_fetch(data)

    @staticmethod
    def _to_source_email(raw, unread):
        message = BytesParser(policy=policy.default).parsebytes(raw)

        # The parser does not raise on rubbish -- a truncated IMAP literal comes
        # back as a Message with no headers at all rather than as an error. That
        # is worth catching rather than displaying: with no Message-ID, no From,
        # no Subject and no Date, headers.py derives the id by hashing the empty
        # seed, so *every* such message would share one id and therefore one
        # entry in the summary cache. A blank row in the inbox is cosmetic; two
        # different messages showing the same cached summary is not.
        if not any(message.get(name) for name in ("Message-ID", "From", "Subject", "Date")):
            raise ValueError("message has no usable headers")

        # Read state is the IMAP flag, never the header. X-Unread is the
        # fixture source's stand-in for that flag (headers.py), and a sender
        # could otherwise set it themselves and so decide how their own mail
        # appears in someone else's inbox.
        del message["X-Unread"]
        message["X-Unread"] = "1" if unread else "0"
        return parse_message(message)

    # --- EmailSource -------------------------------------------------------

    def list_emails(self):
        with self._session() as conn:
            fetched = self._fetch(conn, self._recent_uids(conn), headers_only=False)

        emails = []
        for uid, unread, raw in fetched:
            try:
                emails.append(self._to_source_email(raw, unread))
            except Exception as exc:
                # One malformed message must not empty the whole inbox. The UID
                # identifies it for debugging; the content is not logged.
                log.warning(
                    "Skipping unparseable Gmail message uid=%s (%s)",
                    uid.decode("ascii", "replace"), type(exc).__name__,
                )
        # Newest first, by Date. UID order is arrival order, which is not the
        # same thing, and an unparseable Date sorts last rather than crashing.
        emails.sort(key=lambda e: e.received_at or "", reverse=True)
        log.info("gmail: fetched %d message(s) from %s", len(emails), self.mailbox)
        return emails

    def get_email(self, email_id):
        """Locate one message by id, decoding the body of at most one of them.

        Headers alone are enough to compute the id (headers.message_id_of), so
        the search pass fetches BODY.PEEK[HEADER] and only the match is fetched
        in full -- the same two-pass shape FixtureEmailSource uses, for the same
        reason: no body is decoded except the one being returned.
        """
        with self._session() as conn:
            for uid, _unread, raw in self._fetch(conn, self._recent_uids(conn), headers_only=True):
                headers = BytesParser(policy=policy.default).parsebytes(raw)
                if message_id_of(headers) != email_id:
                    continue
                full = self._fetch(conn, [uid], headers_only=False)
                if not full:
                    # It was there a moment ago and is not now: deleted or moved
                    # between the two fetches. "No such message" is the honest
                    # answer, and the route turns it into a 404.
                    return None
                _uid, unread, body = full[0]
                return self._to_source_email(body, unread)
        return None
