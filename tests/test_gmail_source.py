"""The Gmail source (backend/adapters/gmail_source.py).

No test here talks to Gmail. A fake IMAP server stands in, which is the only
way these properties can be asserted at all: whether the mailbox was opened
read-only, whether the fetch used BODY.PEEK, and whether a failed login leaks
the password are all decided by the *commands sent*, and a live connection
would hide them behind a successful result.

The parsing side is not stubbed. Real RFC-822 bytes go through the real
BytesParser and the real headers.parse_message, so a change to header handling
breaks these tests the same way it breaks the fixture source.
"""

import imaplib
from email.message import EmailMessage

import pytest

from backend.adapters import gmail_source as gmail_module
from backend.adapters.email_source import EmailSourceError, get_email_source
from backend.adapters.gmail_source import GmailImapSource
from backend.config import Config, ConfigError

PASSWORD = "abcdefghijklmnop"


def _message(subject, sender, body, message_id, date="Mon, 8 Sep 2025 09:15:00 +1000",
             extra_headers=()):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "you@example.com"
    message["Subject"] = subject
    message["Date"] = date
    message["Message-ID"] = f"<{message_id}>"
    for name, value in extra_headers:
        message[name] = value
    message.set_content(body)
    return message.as_bytes()


class FakeIMAP:
    """Enough IMAP to answer the three commands the adapter sends.

    Records every call so the tests can assert on what was sent rather than on
    what came back.
    """

    instances = []
    login_error = None

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages = {}       # uid (bytes) -> (raw bytes, flags bytes)
        self.calls = []
        self.selected = None
        self.readonly = None
        self.closed = False
        self.logged_out = False
        self.select_status = "OK"
        FakeIMAP.instances.append(self)

    # --- commands ----------------------------------------------------------

    def login(self, username, password):
        self.calls.append(("login", username))
        if FakeIMAP.login_error:
            raise imaplib.IMAP4.error(FakeIMAP.login_error)
        self.username = username
        return "OK", [b"success"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        self.selected = mailbox
        self.readonly = readonly
        return self.select_status, [b"1"]

    def uid(self, command, *args):
        self.calls.append((command.upper(),) + args)
        if command.upper() == "SEARCH":
            return "OK", [b" ".join(sorted(self.messages, key=int))]
        if command.upper() == "FETCH":
            return "OK", self._fetch(args[0], args[1])
        raise AssertionError(f"unexpected command {command}")

    def close(self):
        self.closed = True

    def logout(self):
        self.logged_out = True

    # --- fetch response building -------------------------------------------

    def _fetch(self, uid_set, what):
        headers_only = "HEADER" in what
        out = []
        for index, uid in enumerate(uid_set.split(b","), start=1):
            raw, flags = self.messages[uid]
            payload = raw.split(b"\n\n", 1)[0] + b"\n\n" if headers_only else raw
            section = b"BODY[HEADER]" if headers_only else b"BODY[]"
            prefix = (
                str(index).encode() + b" (UID " + uid + b" FLAGS (" + flags + b") "
                + section + b" {" + str(len(payload)).encode() + b"}"
            )
            out.append((prefix, payload))
            out.append(b")")   # the terminator imaplib interleaves
        return out


@pytest.fixture(autouse=True)
def fake_imap(monkeypatch):
    FakeIMAP.instances = []
    FakeIMAP.login_error = None
    monkeypatch.setattr(gmail_module.imaplib, "IMAP4_SSL", FakeIMAP)
    yield FakeIMAP


@pytest.fixture
def source():
    return GmailImapSource(
        host="imap.gmail.com", port=993, username="project@example.com",
        password=PASSWORD, mailbox="INBOX", limit=25,
    )


def _load(messages):
    """Seed the next FakeIMAP instance by pre-registering a factory hook."""
    def factory(host, port, timeout=None):
        server = FakeIMAP(host, port, timeout)
        server.messages = dict(messages)
        return server
    return factory


@pytest.fixture
def mailbox(monkeypatch):
    """Install a mailbox that every connection in the test will see."""
    def install(messages):
        monkeypatch.setattr(gmail_module.imaplib, "IMAP4_SSL", _load(messages))
        return messages
    return install


# --- reading ---------------------------------------------------------------


def test_list_emails_parses_and_sorts_newest_first(source, mailbox):
    mailbox({
        b"1": (_message("Older one", "Ada <ada@example.org>", "First body.",
                        "old@example.org", "Mon, 1 Sep 2025 09:00:00 +1000"), b""),
        b"2": (_message("Newer one", "Grace <grace@example.org>", "Second body.",
                        "new@example.org", "Fri, 5 Sep 2025 09:00:00 +1000"), b"\\Seen"),
    })

    emails = source.list_emails()

    assert [e.subject for e in emails] == ["Newer one", "Older one"]
    assert emails[0].sender == "grace@example.org"
    assert emails[0].sender_name == "Grace"
    assert "Second body." in emails[0].body_text


def test_unread_comes_from_the_imap_flag(source, mailbox):
    mailbox({
        b"1": (_message("Unseen", "a@example.org", "b", "u@example.org"), b""),
        b"2": (_message("Seen", "a@example.org", "b", "s@example.org"), b"\\Seen \\Answered"),
    })

    by_subject = {e.subject: e.unread for e in source.list_emails()}

    assert by_subject == {"Unseen": True, "Seen": False}


def test_a_sender_cannot_set_their_own_read_state(source, mailbox):
    """X-Unread is the fixture format's stand-in for the IMAP flag.

    A real sender can put that header on a message they send. If it were
    trusted, a sender would get to decide whether their mail looks unread in
    someone else's inbox -- so the flag overrides it in both directions.
    """
    mailbox({
        b"1": (_message("Marked read by sender", "spam@example.org", "b",
                        "x@example.org", extra_headers=[("X-Unread", "0")]), b""),
        b"2": (_message("Marked unread by sender", "spam@example.org", "b",
                        "y@example.org", extra_headers=[("X-Unread", "1")]), b"\\Seen"),
    })

    by_subject = {e.subject: e.unread for e in source.list_emails()}

    assert by_subject["Marked read by sender"] is True
    assert by_subject["Marked unread by sender"] is False


def test_one_unparseable_message_does_not_empty_the_inbox(source, mailbox, caplog):
    mailbox({
        b"1": (b"\x00 not a message at all", b""),
        b"2": (_message("Fine", "a@example.org", "b", "ok@example.org"), b""),
    })

    emails = source.list_emails()

    assert [e.subject for e in emails] == ["Fine"]


def test_get_email_returns_the_matching_message(source, mailbox):
    mailbox({
        b"1": (_message("One", "a@example.org", "First body.", "one@example.org"), b""),
        b"2": (_message("Two", "b@example.org", "Second body.", "two@example.org"), b""),
    })

    found = source.get_email("two@example.org")

    assert found.subject == "Two"
    assert "Second body." in found.body_text


def test_get_email_returns_none_for_an_unknown_id(source, mailbox):
    mailbox({b"1": (_message("One", "a@example.org", "b", "one@example.org"), b"")})

    assert source.get_email("nothing@example.org") is None


def test_get_email_decodes_one_body_not_the_whole_mailbox(source, mailbox):
    """The search pass is headers-only; only the match is fetched in full."""
    mailbox({
        b"1": (_message("One", "a@example.org", "b", "one@example.org"), b""),
        b"2": (_message("Two", "b@example.org", "b", "two@example.org"), b""),
        b"3": (_message("Three", "c@example.org", "b", "three@example.org"), b""),
    })

    source.get_email("three@example.org")

    fetches = [call for call in FakeIMAP.instances[0].calls if call[0] == "FETCH"]
    assert len(fetches) == 2
    assert "HEADER" in fetches[0][2]          # the search pass, all three
    assert fetches[1][1] == b"3"              # the body pass, one message
    assert "HEADER" not in fetches[1][2]


def test_only_the_newest_limit_messages_are_fetched(mailbox):
    source = GmailImapSource("imap.gmail.com", 993, "u@example.com", PASSWORD, limit=2)
    mailbox({
        str(uid).encode(): (_message(f"Message {uid}", "a@example.org", "b",
                                     f"{uid}@example.org"), b"")
        for uid in range(1, 6)
    })

    source.list_emails()

    fetches = [call for call in FakeIMAP.instances[0].calls if call[0] == "FETCH"]
    assert fetches[0][1] == b"4,5"


# --- read-only, which is the claim that matters ----------------------------


def test_the_mailbox_is_opened_read_only(source, mailbox):
    mailbox({b"1": (_message("One", "a@example.org", "b", "one@example.org"), b"")})

    source.list_emails()

    server = FakeIMAP.instances[0]
    assert server.readonly is True
    assert server.selected == '"INBOX"'


def test_bodies_are_fetched_with_peek_so_nothing_is_marked_read(source, mailbox):
    mailbox({b"1": (_message("One", "a@example.org", "b", "one@example.org"), b"")})

    source.list_emails()

    fetches = [call for call in FakeIMAP.instances[0].calls if call[0] == "FETCH"]
    assert fetches, "no fetch was issued"
    for call in fetches:
        assert "BODY.PEEK" in call[2]
        assert "RFC822" not in call[2]


def test_no_command_can_change_the_mailbox(source, mailbox):
    mailbox({b"1": (_message("One", "a@example.org", "b", "one@example.org"), b"")})

    source.list_emails()
    source.get_email("one@example.org")

    sent = {call[0] for server in FakeIMAP.instances for call in server.calls}
    assert sent <= {"login", "select", "SEARCH", "FETCH"}


def test_the_connection_is_closed_even_when_the_fetch_fails(source, mailbox):
    mailbox({b"1": (_message("One", "a@example.org", "b", "one@example.org"), b"")})
    server_box = []

    def exploding_uid(self, command, *args):
        server_box.append(self)
        raise imaplib.IMAP4.error("server went away")

    original = FakeIMAP.uid
    try:
        FakeIMAP.uid = exploding_uid
        with pytest.raises(EmailSourceError):
            source.list_emails()
    finally:
        FakeIMAP.uid = original

    assert server_box[0].logged_out is True


# --- failure messages ------------------------------------------------------


def test_a_rejected_login_does_not_leak_the_password(source, mailbox):
    mailbox({})
    FakeIMAP.login_error = f"AUTHENTICATIONFAILED credentials rejected ({PASSWORD})"

    with pytest.raises(EmailSourceError) as raised:
        source.list_emails()

    message = str(raised.value)
    assert PASSWORD not in message
    assert "app password" in message


def test_a_missing_mailbox_names_the_setting_to_change(mailbox):
    source = GmailImapSource("imap.gmail.com", 993, "u@example.com", PASSWORD,
                             mailbox="Studies")
    mailbox({})
    FakeIMAP.instances = []

    def failing_select(self, name, readonly=False):
        self.calls.append(("select", name, readonly))
        return "NO", [b"Unknown Mailbox"]

    original = FakeIMAP.select
    try:
        FakeIMAP.select = failing_select
        with pytest.raises(EmailSourceError) as raised:
            source.list_emails()
    finally:
        FakeIMAP.select = original

    assert "GMAIL_MAILBOX" in str(raised.value)


def test_an_unreachable_server_is_not_reported_as_an_empty_mailbox(source, monkeypatch):
    def refuse(host, port, timeout=None):
        raise OSError(61, "Connection refused")

    monkeypatch.setattr(gmail_module.imaplib, "IMAP4_SSL", refuse)

    with pytest.raises(EmailSourceError) as raised:
        source.list_emails()

    assert "imap.gmail.com:993" in str(raised.value)


# --- wiring ----------------------------------------------------------------


def test_the_factory_builds_the_gmail_source(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("EMAIL_SOURCE", "gmail_imap")
    monkeypatch.setenv("GMAIL_USER", "project@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("GMAIL_MAILBOX", "INBOX")
    config = Config(require_llm=False)

    source = get_email_source(config)

    assert isinstance(source, GmailImapSource)
    assert source.username == "project@example.com"


def test_gmail_without_credentials_fails_at_startup_not_at_first_request(monkeypatch):
    """A missing app password is a misconfiguration, and section 1 says those
    surface when the process starts rather than when a user first loads the
    inbox."""
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("EMAIL_SOURCE", "gmail_imap")
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

    with pytest.raises(ConfigError) as raised:
        Config(require_llm=False)

    assert "GMAIL_USER" in str(raised.value)


def test_the_fixture_source_is_untouched_by_the_new_branch(config):
    """EMAIL_SOURCE is unset in the test environment, so the default still wins."""
    from backend.adapters.email_source import FixtureEmailSource

    assert isinstance(get_email_source(config), FixtureEmailSource)
