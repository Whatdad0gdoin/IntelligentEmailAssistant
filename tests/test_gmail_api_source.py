"""The Gmail API source (backend/adapters/gmail_api_source.py).

No test here touches Google. A fake service stands in for googleapiclient's,
built so that it only answers the three calls the adapter is allowed to make --
messages.list, messages.get and labels.list. Anything else raises. That turns
"the app never modifies your mailbox" from a claim in a docstring into
something the suite fails on.
"""

import base64
import json
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
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
            if format == "full":
                message = BytesParser(policy=policy.default).parsebytes(_unb64(record["raw"]))
                payload = _gmail_tree(message, "", self._gmail.decoded_headers,
                                      record.get("out_of_line", ()))
                return {"id": id, "labelIds": record["labelIds"], "payload": payload}
            # metadata: Gmail matches the requested names without regard to
            # case and returns each header under the name the message used.
            wanted = {n.lower() for n in (metadataHeaders or [])}
            headers = [{"name": n, "value": v} for n, v in record["headers"]
                       if n.lower() in wanted]
            return {"id": id, "labelIds": record["labelIds"], "payload": {"headers": headers}}
        return _Request(run)


def _unb64(raw):
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _gmail_tree(part, part_id, decoded_headers, out_of_line):
    """The format=full payload Gmail builds from one MIME part.

    Modelled on Gmail's documented behaviour: header values as they appear in
    the message (unfolded), text parts without a file name carry their bytes
    inline as body.data, anything named or binary is an attachment -- an
    attachmentId and a size, never data -- and an attached message/rfc822
    nests the forwarded message's own tree. `out_of_line` lists body types to
    push out of line as well, to exercise the adapter's raw fallback.
    """
    content_type = part.get_content_type()
    if decoded_headers:
        headers = [{"name": n, "value": str(v)} for n, v in part.items()]
    else:
        headers = [{"name": n, "value": re.sub(r"\r?\n(?=[ \t])", "", str(v))}
                   for n, v in part.raw_items()]
    node = {"partId": part_id, "mimeType": content_type,
            "filename": part.get_filename() or "", "headers": headers}
    child_id = (lambda i: f"{part_id}.{i}" if part_id else str(i))
    if content_type == "message/rfc822":
        inner = part.get_payload(0)
        node["body"] = {"size": len(inner.as_bytes())}
        node["parts"] = [_gmail_tree(inner, child_id(0), decoded_headers, out_of_line)]
    elif part.is_multipart():
        node["body"] = {"size": 0}
        node["parts"] = [_gmail_tree(c, child_id(i), decoded_headers, out_of_line)
                         for i, c in enumerate(part.get_payload())]
    else:
        data = part.get_payload(decode=True) or b""
        inline = (not node["filename"] and content_type in ("text/plain", "text/html")
                  and content_type not in out_of_line)
        if inline:
            node["body"] = {"size": len(data), "data": base64.urlsafe_b64encode(data).decode()}
        else:
            node["body"] = {"attachmentId": f"ANG-{part_id or 'root'}", "size": len(data)}
    return node


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
        # False: header values come back as they appear in the message, encoded
        # words and all. True: already decoded. Gmail is not documented either
        # way, so the adapter is tested against both.
        self.decoded_headers = False

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
        return self.add_message(gid, message, unread=unread, labels=labels,
                                msgid=msgid or gid + "@mail.example.org")

    def add_message(self, gid, message, unread=True, labels=("INBOX",), msgid=None,
                    out_of_line=()):
        """Store any EmailMessage, attachments and all."""
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        label_ids = list(labels) + (["UNREAD"] if unread else [])
        wanted = ("message-id", "from", "subject", "date")
        record = {
            "id": gid, "raw": raw, "labelIds": label_ids,
            "msgid": msgid or str(message.get("Message-ID", "")).strip("<>"),
            # Kept under the names the message itself used, as Gmail does.
            "headers": [(n, str(v)) for n, v in message.items() if n.lower() in wanted],
            "out_of_line": tuple(out_of_line),
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
                           "msgid": "", "headers": []})
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
    body_fetches = [c for c in gmail.get_calls if c[1] in ("full", "raw")]
    assert body_fetches == [(body_fetches[0][0], "full")], gmail.get_calls


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
        subject = dict(gmail.by_id[gid]["headers"])["Subject"]
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


# --- format=full: attachments stay on Google's side -----------------------------


def _report(gid="a1", subject="Report attached", message_id=None):
    message = EmailMessage()
    message["From"] = "Grace Hopper <grace@example.org>"
    message["To"] = "project@gmail.com"
    message["Subject"] = subject
    message["Message-ID"] = f"<{message_id or gid + '@mail.example.org'}>"
    message["Date"] = format_datetime(datetime(2026, 9, 2, tzinfo=timezone.utc))
    message.set_content("The figures are in the PDF.")
    message.add_alternative("<p>The figures are in the PDF.</p>", subtype="html")
    message.add_attachment(b"%PDF-1.4 " + b"x" * 5000, maintype="application",
                           subtype="pdf", filename="Q3 figures.pdf")
    message.add_attachment("ATTACHMENT-BODY-MARKER", filename="notes.txt")
    return message


def test_the_inbox_never_downloads_an_attachment():
    """format=raw carries every attachment inline; the inbox must never use it
    when the body text came back with the message."""
    gmail = FakeGmail()
    gmail.add_message("a1", _report())
    gmail.add("g2", "Plain one")
    emails = _source(gmail).list_emails()

    assert {fmt for _gid, fmt in gmail.get_calls} == {"full"}
    report = next(e for e in emails if e.subject == "Report attached")
    assert [(a.filename, a.content_type, a.size) for a in report.attachments] == [
        ("Q3 figures.pdf", "application/pdf", 5009),
        ("notes.txt", "text/plain", len("ATTACHMENT-BODY-MARKER") + 1),
    ]
    assert "ATTACHMENT-BODY-MARKER" not in report.body_text + report.body_html
    assert "The figures are in the PDF." in report.body_text


def _sample_messages():
    """Shapes worth proving format=full and format=raw agree on."""
    plain = EmailMessage()
    plain["From"] = "Ada Lovelace <ada@example.org>"
    plain["To"] = "project@gmail.com"
    plain["Subject"] = "Plain"
    plain["Message-ID"] = "<plain@example.org>"
    plain["Date"] = format_datetime(datetime(2026, 9, 1, tzinfo=timezone.utc))
    plain.set_content("Just text.")

    accented = EmailMessage()
    accented["From"] = "Zoë Müller <zoe@example.org>"
    accented["To"] = "project@gmail.com"
    accented["Subject"] = "Réunion à 10h, café inclus"
    accented["Message-ID"] = "<accent@example.org>"
    accented["Date"] = format_datetime(datetime(2026, 9, 3, tzinfo=timezone.utc))
    accented["References"] = "<root@example.org> <parent@example.org>"
    accented.set_content("Le café est prêt.", charset="iso-8859-1")
    accented.add_alternative("<p>Le café est prêt.</p>", subtype="html")

    embedded = EmailMessage()
    embedded["From"] = "News <news@example.org>"
    embedded["Subject"] = "Banner"
    embedded["Message-ID"] = "<banner@example.org>"
    embedded["Date"] = format_datetime(datetime(2026, 9, 4, tzinfo=timezone.utc))
    embedded.set_content("Text version.")
    embedded.add_alternative('<p><img src="cid:b1"> HTML version.</p>', subtype="html")
    embedded.get_payload()[1].add_related(b"\x89PNG", maintype="image", subtype="png",
                                         cid="<b1>", filename="banner.png", disposition="inline")

    inner = EmailMessage()
    inner["From"] = "boss@example.org"
    inner["Subject"] = "Original"
    inner.set_content("Forwarded words.")
    inner.add_attachment(b"PK", maintype="application", subtype="zip", filename="inner.zip")
    forwarded = EmailMessage()
    forwarded["From"] = "Ada Lovelace <ada@example.org>"
    forwarded["Subject"] = "Fwd: Original"
    forwarded["Message-ID"] = "<fwd@example.org>"
    forwarded["Date"] = format_datetime(datetime(2026, 9, 5, tzinfo=timezone.utc))
    forwarded.set_content("See below.")
    forwarded.add_attachment(inner)

    no_id = EmailMessage()
    no_id["From"] = "Ada Lovelace <ada@example.org>"
    no_id["Subject"] = "No Message-ID here"
    no_id["Date"] = format_datetime(datetime(2026, 9, 6, tzinfo=timezone.utc))
    no_id.set_content("Hashed id.")

    return [plain, accented, embedded, _report(), forwarded, no_id]


@pytest.mark.parametrize("decoded_headers", [False, True],
                         ids=["headers-as-sent", "headers-decoded"])
def test_full_and_raw_build_the_same_email(decoded_headers):
    """format=full is only a cheaper way to download the same message. If any
    field differed from the raw parse, an email could change id between the
    inbox and the reading pane, or lose text."""
    for index, message in enumerate(_sample_messages()):
        gmail = FakeGmail()
        gmail.decoded_headers = decoded_headers
        gmail.add_message("m", message)
        via_full = _source(gmail).list_emails()[0]
        raw = gmail.users().messages().get(userId="me", id="m", format="raw").execute()
        via_raw = GmailApiSource._to_source_email(raw)
        assert vars(via_full) == vars(via_raw), f"sample {index} ({message['Subject']})"


def test_an_attached_email_is_listed_never_read_into_the_body():
    """Gmail nests a forwarded message's own parts under its message/rfc822
    part. A walk that checked each part alone read that message's text as
    this one's body, on both paths alike -- which is why the equality test
    above could not catch it."""
    forwarded = next(m for m in _sample_messages() if m["Subject"] == "Fwd: Original")
    gmail = FakeGmail()
    gmail.add_message("f1", forwarded)
    via_full = _source(gmail).list_emails()[0]
    raw = gmail.users().messages().get(userId="me", id="f1", format="raw").execute()
    for email in (via_full, GmailApiSource._to_source_email(raw)):
        assert "Forwarded words." not in email.body_text + email.body_html
        assert email.body_text.strip() == "See below."
        assert [a.content_type for a in email.attachments] == ["message/rfc822"]


def test_body_text_gmail_keeps_out_of_line_is_fetched_whole():
    gmail = FakeGmail()
    gmail.add_message("o1", _report(gid="o1", subject="Long text"), out_of_line=("text/plain",))
    gmail.add("g2", "Ordinary")
    emails = {e.subject: e for e in _source(gmail).list_emails()}

    assert "The figures are in the PDF." in emails["Long text"].body_text
    assert [a.filename for a in emails["Long text"].attachments] == ["Q3 figures.pdf", "notes.txt"]
    assert ("o1", "raw") in gmail.get_calls
    assert ("g2", "raw") not in gmail.get_calls   # only the one that needed it


def test_get_email_falls_back_to_raw_only_when_it_must():
    gmail = FakeGmail()
    gmail.add_message("o1", _report(gid="o1", subject="Long text"), out_of_line=("text/plain",))
    target = _source(gmail).list_emails()[0].id
    gmail.get_calls.clear()
    found = _source(gmail).get_email(target)
    assert found is not None and "The figures are in the PDF." in found.body_text
    assert [fmt for _gid, fmt in gmail.get_calls if fmt != "metadata"] == ["full", "raw"]


def test_a_message_id_header_in_any_case_still_opens():
    """Senders write "Message-Id" as often as "Message-ID". The inbox (format=full)
    and the reading pane's lookup (format=metadata) must agree on the id either
    way, or clicking the email would find nothing."""
    message = EmailMessage()
    message["From"] = "Ada Lovelace <ada@example.org>"
    message["Subject"] = "Lower-case id header"
    message["Message-Id"] = "<CAF+mixed=case@mail.example.org>"
    message["Date"] = format_datetime(datetime(2026, 9, 7, tzinfo=timezone.utc))
    message.set_content("Hello.")
    gmail = FakeGmail()
    gmail.add_message("c1", message, msgid="CAF+mixed=case@mail.example.org")
    listed = _source(gmail).list_emails()[0]
    assert listed.id == "CAF_mixed_case@mail.example.org"   # '+' and '=' sanitised
    opened = _source(gmail).get_email(listed.id)
    assert opened is not None and opened.subject == "Lower-case id header"
