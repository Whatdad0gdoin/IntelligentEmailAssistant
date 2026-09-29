"""The Gmail API source (backend/adapters/gmail_api_source.py).

No test here touches Google. A fake service stands in for googleapiclient's,
built so that it only answers the three calls the adapter is allowed to make --
messages.list, messages.get and labels.list. Anything else raises. That turns
"the app never modifies your mailbox" from a claim in a docstring into
something the suite fails on.
"""

import base64
import json
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httplib2
import pytest
from googleapiclient.errors import HttpError

from backend.adapters.email_source import EmailSourceError, get_email_source
from backend.adapters.gmail_api_source import SCOPES, GmailApiSource, _Credentials
from backend.adapters.headers import message_id_of


# --- fake Gmail --------------------------------------------------------------


class Forbidden(AssertionError):
    pass


class _Guard:
    """Anything not explicitly implemented is a call the adapter must not make."""

    def __getattr__(self, name):
        raise Forbidden(f"adapter called a method it must never use: {name}")


class _Request(_Guard):
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Batch(_Guard):
    def __init__(self, callback, gmail):
        self._callback = callback
        self._items = []
        gmail.batches += 1

    def add(self, request, request_id):
        self._items.append((request_id, request))

    def execute(self):
        for request_id, request in self._items:
            try:
                self._callback(request_id, request.execute(), None)
            except Exception as exc:  # noqa: BLE001 -- mirrors googleapiclient
                self._callback(request_id, None, exc)


class _Messages(_Guard):
    def __init__(self, gmail):
        self._gmail = gmail

    def list(self, userId, labelIds, maxResults, q=None):
        assert userId == "me"
        self._gmail.list_calls.append({"labelIds": labelIds, "q": q, "max": maxResults})
        if self._gmail.list_error:
            return _Request(_raise(self._gmail.list_error))

        def run():
            ids = [m["id"] for m in self._gmail.messages if labelIds[0] in m["labelIds"]]
            if q and q.startswith("rfc822msgid:"):
                wanted = q.split(":", 1)[1]
                ids = [i for i in ids if self._gmail.by_id[i]["msgid"] == wanted]
            return {"messages": [{"id": i} for i in ids[:maxResults]]}
        return _Request(run)

    def get(self, userId, id, format, metadataHeaders=None):
        assert userId == "me"
        self._gmail.get_calls.append((id, format))

        def run():
            if id in self._gmail.broken:
                raise self._gmail.broken[id]
            record = self._gmail.by_id[id]
            if format == "raw":
                return {"id": id, "labelIds": record["labelIds"], "raw": record["raw"]}
            headers = [{"name": n, "value": v} for n, v in record["headers"].items()
                       if n in (metadataHeaders or [])]
            return {"id": id, "labelIds": record["labelIds"], "payload": {"headers": headers}}
        return _Request(run)


class _Labels(_Guard):
    def __init__(self, gmail):
        self._gmail = gmail

    def list(self, userId):
        return _Request(lambda: {"labels": self._gmail.labels})


class _Users(_Guard):
    def __init__(self, gmail):
        self._gmail = gmail

    def messages(self):
        return _Messages(self._gmail)

    def labels(self):
        return _Labels(self._gmail)


class FakeGmail(_Guard):
    def __init__(self):
        self.messages = []
        self.by_id = {}
        self.broken = {}
        self.labels = [{"id": "INBOX", "name": "INBOX"}]
        self.list_calls = []
        self.get_calls = []
        self.batches = 0
        self.list_error = None

    def users(self):
        return _Users(self)

    def new_batch_http_request(self, callback):
        return _Batch(callback, self)

    def add(self, gid, subject, sender="Ada Lovelace <ada@example.org>", body="Hello there.",
            msgid=None, unread=True, labels=("INBOX",), when=None, extra_headers=None):
        message = EmailMessage()
        message["From"] = sender
        message["To"] = "project@gmail.com"
        message["Subject"] = subject
        message["Message-ID"] = f"<{msgid or gid + '@mail.example.org'}>"
        message["Date"] = format_datetime(when or datetime(2026, 9, 1, tzinfo=timezone.utc))
        for name, value in (extra_headers or {}).items():
            message[name] = value
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        label_ids = list(labels) + (["UNREAD"] if unread else [])
        record = {
            "id": gid, "raw": raw, "labelIds": label_ids,
            "msgid": (msgid or gid + "@mail.example.org"),
            "headers": {k: message[k] for k in ("Message-ID", "From", "Subject", "Date")},
        }
        self.messages.append(record)
        self.by_id[gid] = record
        return message


def _raise(exc):
    def run():
        raise exc
    return run


def _http_error(status, reason=None):
    body = {"error": {"code": status, "errors": [{"reason": reason}] if reason else []}}
    return HttpError(httplib2.Response({"status": status}), json.dumps(body).encode())


def _source(gmail, **kwargs):
    return GmailApiSource(token_path="unused", service=gmail, **kwargs)


# --- reading ------------------------------------------------------------------


def test_messages_come_back_as_parsed_source_emails():
    gmail = FakeGmail()
    gmail.add("g1", "Budget sign-off", sender="Andrea Lawson <a.lawson@northgate.com.au>")
    emails = _source(gmail).list_emails()
    assert len(emails) == 1
    assert emails[0].subject == "Budget sign-off"
    assert emails[0].sender == "a.lawson@northgate.com.au"
    assert emails[0].sender_name == "Andrea Lawson"
    assert "Hello there" in emails[0].raw_body


def test_newest_first():
    gmail = FakeGmail()
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    gmail.add("old", "Old", when=base)
    gmail.add("new", "New", when=base + timedelta(days=2))
    gmail.add("mid", "Mid", when=base + timedelta(days=1))
    assert [e.subject for e in _source(gmail).list_emails()] == ["New", "Mid", "Old"]


def test_unread_comes_from_gmail_not_from_the_sender():
    """A sender can put X-Unread: 1 in their own message. Read state must come
    from Gmail's UNREAD label, or senders decide how their mail looks to you."""
    gmail = FakeGmail()
    gmail.add("g1", "Already read", unread=False, extra_headers={"X-Unread": "1"})
    gmail.add("g2", "Not read yet", unread=True)
    by_subject = {e.subject: e for e in _source(gmail).list_emails()}
    assert by_subject["Already read"].unread is False
    assert by_subject["Not read yet"].unread is True


def test_only_the_configured_label_is_read():
    gmail = FakeGmail()
    gmail.add("g1", "In the inbox")
    gmail.add("g2", "Filed in spam", labels=("SPAM",))
    assert [e.subject for e in _source(gmail).list_emails()] == ["In the inbox"]


def test_the_limit_is_respected():
    gmail = FakeGmail()
    for i in range(10):
        gmail.add(f"g{i}", f"Message {i}")
    assert len(_source(gmail, limit=4).list_emails()) == 4


def test_large_inboxes_are_fetched_in_batches_of_fifty():
    gmail = FakeGmail()
    for i in range(120):
        gmail.add(f"g{i}", f"Message {i}")
    assert len(_source(gmail, limit=120).list_emails()) == 120
    assert gmail.batches == 3


def test_a_user_label_is_found_by_its_name():
    gmail = FakeGmail()
    gmail.labels.append({"id": "Label_42", "name": "FIT3164 Demo"})
    gmail.add("g1", "Demo message", labels=("Label_42",))
    gmail.add("g2", "Everything else")
    assert [e.subject for e in _source(gmail, label="fit3164 demo").list_emails()] == ["Demo message"]


def test_an_unknown_label_is_a_clear_error():
    gmail = FakeGmail()
    with pytest.raises(EmailSourceError, match="no label called"):
        _source(gmail, label="Nonexistent").list_emails()


# --- resilience ----------------------------------------------------------------


def test_one_bad_message_does_not_empty_the_inbox():
    gmail = FakeGmail()
    gmail.add("g1", "Fine")
    gmail.add("g2", "Also fine")
    gmail.broken["g2"] = _http_error(404)
    assert [e.subject for e in _source(gmail).list_emails()] == ["Fine"]


def test_if_every_fetch_fails_that_is_an_error_not_an_empty_inbox():
    """An empty inbox would hide a broken connection behind a normal-looking
    screen."""
    gmail = FakeGmail()
    gmail.add("g1", "One")
    gmail.add("g2", "Two")
    gmail.broken["g1"] = _http_error(401)
    gmail.broken["g2"] = _http_error(401)
    with pytest.raises(EmailSourceError, match="Reconnect"):
        _source(gmail).list_emails()


def test_a_headerless_message_is_skipped():
    gmail = FakeGmail()
    gmail.add("g1", "Real")
    gmail.messages.append({"id": "g2", "labelIds": ["INBOX"],
                           "raw": base64.urlsafe_b64encode(b"\r\n\r\njust a body").decode(),
                           "msgid": "", "headers": {}})
    gmail.by_id["g2"] = gmail.messages[-1]
    assert [e.subject for e in _source(gmail).list_emails()] == ["Real"]


# --- finding one message -----------------------------------------------------


def test_get_email_by_the_apps_own_id():
    gmail = FakeGmail()
    message = gmail.add("g1", "Target")
    gmail.add("g2", "Other")
    found = _source(gmail).get_email(message_id_of(message))
    assert found is not None and found.subject == "Target"


def test_get_email_downloads_one_body_only():
    gmail = FakeGmail()
    for i in range(8):
        gmail.add(f"g{i}", f"Message {i}")
    target = _source(gmail).list_emails()[5].id
    gmail.get_calls.clear()

    _source(gmail).get_email(target)
    raw_fetches = [c for c in gmail.get_calls if c[1] == "raw"]
    assert len(raw_fetches) == 1, gmail.get_calls


def test_get_email_finds_a_message_whose_id_was_sanitised():
    """Gmail Message-IDs often contain '+' and '='. Our ids turn those into
    underscores, so a Gmail search by our id misses -- the fallback has to find
    it anyway."""
    gmail = FakeGmail()
    gmail.add("g1", "Tricky id", msgid="CAF+abc=xyz@mail.gmail.com")
    gmail.add("g2", "Plain")
    our_id = next(e.id for e in _source(gmail).list_emails() if e.subject == "Tricky id")
    assert "+" not in our_id and "=" not in our_id

    found = _source(gmail).get_email(our_id)
    assert found is not None and found.subject == "Tricky id"


def test_get_email_unknown_id_is_none():
    gmail = FakeGmail()
    gmail.add("g1", "Only one")
    assert _source(gmail).get_email("no-such-id@nowhere") is None


def test_metadata_ids_match_full_parse_ids():
    """The fallback computes ids from headers alone. If that ever disagreed with
    the id the inbox shows, opening a message would silently fail."""
    gmail = FakeGmail()
    gmail.add("g1", "Normal", msgid="normal@example.org")
    gmail.add("g2", "Odd id", msgid="CAF+abc==q/x@mail.gmail.com")
    gmail.add("g3", "Unicode subject été")
    source = _source(gmail)
    full = {e.subject: e.id for e in source.list_emails()}
    for gid in ("g1", "g2", "g3"):
        meta = gmail.users().messages().get(userId="me", id=gid, format="metadata",
                                           metadataHeaders=["Message-ID", "From", "Subject", "Date"]).execute()
        subject = gmail.by_id[gid]["headers"]["Subject"]
        assert source._id_from_metadata(meta) == full[subject]


# --- read-only -------------------------------------------------------------------


def test_the_only_scope_requested_is_read_only():
    """Widening this must be a deliberate, visible change."""
    assert SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_reading_and_opening_never_touch_a_mutating_call():
    """The fake raises Forbidden on anything but list/get/labels.list, so this
    passing means no modify, trash, send, batchModify or label change was
    attempted along either path the app uses."""
    gmail = FakeGmail()
    gmail.labels.append({"id": "Label_1", "name": "Demo"})
    gmail.add("g1", "One", labels=("Label_1",))
    source = _source(gmail, label="Demo")
    emails = source.list_emails()
    source.get_email(emails[0].id)


def test_no_mutating_gmail_method_appears_in_the_adapter_source():
    import inspect

    import backend.adapters.gmail_api_source as module
    source = inspect.getsource(module)
    for verb in ("modify(", "batchModify", "trash(", "untrash(", ".delete(",
                 ".send(", ".insert(", ".import_(", "drafts("):
        assert verb not in source, f"adapter references {verb}"


# --- errors a person can act on --------------------------------------------------


@pytest.mark.parametrize("status,reason,expected", [
    (401, None, "Reconnect"),
    (403, "accessNotConfigured", "not enabled"),
    (403, "insufficientPermissions", "read access"),
    (403, "rateLimitExceeded", "rate limiting"),
    (429, None, "rate limiting"),
    (503, None, "trouble"),
])
def test_api_failures_become_actionable_messages(status, reason, expected):
    gmail = FakeGmail()
    gmail.list_error = _http_error(status, reason)
    with pytest.raises(EmailSourceError, match=expected):
        _source(gmail).list_emails()


def test_a_network_failure_is_reported_as_one():
    gmail = FakeGmail()
    gmail.list_error = OSError("connection reset")
    with pytest.raises(EmailSourceError, match="Could not reach Gmail"):
        _source(gmail).list_emails()


def test_no_body_reaches_the_log(caplog):
    gmail = FakeGmail()
    secret = "the merger closes on the fourteenth for nine million"
    gmail.add("g1", "Numbers", body=secret)
    with caplog.at_level("DEBUG"):
        _source(gmail).list_emails()
    assert secret not in caplog.text


# --- credentials -----------------------------------------------------------------


def test_a_missing_token_says_how_to_connect(tmp_path):
    with pytest.raises(EmailSourceError, match="not connected.*gmail_auth"):
        _Credentials(str(tmp_path / "absent.json")).get()


def test_an_unreadable_token_says_how_to_reconnect(tmp_path):
    bad = tmp_path / "token.json"
    bad.write_text("this is not json", encoding="utf-8")
    with pytest.raises(EmailSourceError, match="unreadable"):
        _Credentials(str(bad)).get()


def test_the_seven_day_expiry_is_explained(tmp_path, monkeypatch):
    """The failure most likely to appear on demo day, so the message names it."""
    from google.auth.exceptions import RefreshError

    class Expired:
        valid = False
        refresh_token = "r"
        scopes = SCOPES

        def refresh(self, request):
            raise RefreshError("invalid_grant")

    store = _Credentials(str(tmp_path / "token.json"))
    monkeypatch.setattr(store, "_load", lambda: Expired())
    with pytest.raises(EmailSourceError, match="7 days.*gmail_auth"):
        store.get()


def test_a_refreshed_token_is_saved_back(tmp_path, monkeypatch):
    """Otherwise every restart spends a refresh, and a refresh that rotates the
    token would be lost."""

    class Refreshable:
        valid = False
        refresh_token = "r"
        scopes = SCOPES

        def refresh(self, request):
            self.valid = True

        def to_json(self):
            return json.dumps({"refreshed": True})

    path = tmp_path / "token.json"
    store = _Credentials(str(path))
    monkeypatch.setattr(store, "_load", lambda: Refreshable())
    store.get()
    assert json.loads(path.read_text(encoding="utf-8")) == {"refreshed": True}


# --- selection ---------------------------------------------------------------------


def test_email_source_gmail_selects_the_api_adapter(monkeypatch):
    from backend.config import Config

    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("EMAIL_SOURCE", "gmail")
    config = Config(require_llm=False)
    assert isinstance(get_email_source(config), GmailApiSource)


def test_the_api_source_needs_no_imap_password(monkeypatch):
    from backend.config import Config

    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("EMAIL_SOURCE", "gmail")
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    Config(require_llm=False)   # must not raise
