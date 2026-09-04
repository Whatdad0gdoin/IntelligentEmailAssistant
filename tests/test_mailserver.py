"""The local mail server (backend/mailserver.py).

Two things are being checked here.

First, that delivery works end to end: a real SMTP conversation puts a message
in the delivery directory, and the app's own email source then returns it
alongside the fixtures.

Second, and more important for the report, that the tier separation holds. The
mail server persists email because that is what a mailbox does; the Flask API
does not, which is what NFR-03 actually constrains. That claim is only worth
making if nothing in the app imports this module, so a test asserts it rather
than trusting the file layout.
"""

import os
import smtplib
import socket
import time
from email.message import EmailMessage

import pytest

from backend.adapters.email_source import FixtureEmailSource, get_email_source
from backend.mailserver import MailboxHandler, build_controller


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _message(subject="Hello there", sender="Ada Lovelace <ada@example.org>",
             body="This is the body of a test message.\n"):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "you@mailkit.local"
    message["Subject"] = subject
    message.set_content(body)
    return message


@pytest.fixture
def inbox_dir(config, tmp_path):
    """The directory the mail server delivers into, per the test config."""
    path = config.email_inbox_dir
    os.makedirs(path, exist_ok=True)
    return path


@pytest.fixture
def running_server(config, inbox_dir):
    config.smtp_host = "127.0.0.1"
    config.smtp_port = _free_port()
    controller = build_controller(config, directory=inbox_dir)
    controller.start()
    yield config
    controller.stop()


def _send(config, message):
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


def _delivered(directory):
    return [n for n in os.listdir(directory) if n.endswith(".eml")]


# --- Delivery ---------------------------------------------------------------


def test_a_sent_message_is_written_to_the_delivery_directory(running_server, inbox_dir):
    _send(running_server, _message())
    assert len(_delivered(inbox_dir)) == 1


def test_a_delivered_message_appears_in_the_app_mailbox(running_server, inbox_dir):
    """The whole point: send an email, open it in the app."""
    before = len(get_email_source(running_server).list_emails())
    _send(running_server, _message(subject="Coffee on Thursday?"))
    after = get_email_source(running_server).list_emails()

    assert len(after) == before + 1
    match = [e for e in after if e.subject == "Coffee on Thursday?"]
    assert len(match) == 1
    assert match[0].sender == "ada@example.org"
    assert "body of a test message" in match[0].raw_body


def test_the_committed_fixtures_are_still_there(running_server, inbox_dir):
    """Delivery adds to the mailbox; it must not replace or hide the demo set."""
    _send(running_server, _message())
    subjects = {e.subject for e in get_email_source(running_server).list_emails()}
    assert "Project deadline moved to Friday" in subjects


def test_new_mail_arrives_unread(running_server, inbox_dir):
    _send(running_server, _message(subject="Unread please"))
    match = next(e for e in get_email_source(running_server).list_emails()
                 if e.subject == "Unread please")
    assert match.unread is True


def test_the_same_message_sent_twice_produces_two_distinct_emails(running_server, inbox_dir):
    """Without a Message-ID, headers.py derives the id from From|Subject|Date.
    Two identical sends in the same second would then collide and the second
    would silently never appear."""
    _send(running_server, _message(subject="Duplicate"))
    _send(running_server, _message(subject="Duplicate"))

    emails = [e for e in get_email_source(running_server).list_emails()
              if e.subject == "Duplicate"]
    assert len(emails) == 2
    assert emails[0].id != emails[1].id


def test_a_message_with_no_date_still_sorts_and_parses(running_server, inbox_dir):
    message = _message(subject="No date header")
    del message["Date"]
    _send(running_server, message)
    match = next(e for e in get_email_source(running_server).list_emails()
                 if e.subject == "No date header")
    assert match.received_at, "a Date should have been supplied on delivery"


def test_delivery_is_atomic(running_server, inbox_dir):
    """Files are renamed into place, so the API never reads a half-written one."""
    _send(running_server, _message())
    leftovers = [n for n in os.listdir(inbox_dir) if n.endswith(".part")]
    assert leftovers == []


def test_a_missing_delivery_directory_is_not_an_error(config, tmp_path):
    """The directory legitimately does not exist until the first message."""
    source = FixtureEmailSource(
        config.email_fixture_dir, extra_dirs=(str(tmp_path / "never-created"),)
    )
    assert len(source.list_emails()) > 0


# --- Tier separation (NFR-03) -----------------------------------------------


def test_no_application_module_imports_the_mail_server():
    """The mail server persists email; the assistant does not. That distinction
    is only meaningful if the app cannot reach this module, so check the source
    rather than the intent."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "backend"
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        # config.py holds the SMTP host and port, which is settings rather
        # than a dependency, so an import is what counts here and a comment
        # mentioning the module is not. The sender lives in tools/, outside
        # backend/ entirely, because it imports smtplib.
        if rel == "mailserver.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any("mailserver" in n for n in names):
                offenders.append(rel)
    assert not offenders, f"application code imports the mail server: {offenders}"


def test_the_handler_never_logs_a_body(running_server, inbox_dir, caplog):
    """NFR-03 logging discipline applies here too, even though this tier is
    allowed to write the message to disk."""
    secret = "quarterly revenue was fourteen million dollars"
    with caplog.at_level("INFO"):
        _send(running_server, _message(subject="Numbers", body=secret + "\n"))
        time.sleep(0.1)
    assert secret not in caplog.text


def test_the_handler_writes_only_into_its_own_directory(inbox_dir):
    """A subject cannot escape the delivery directory: filenames come from the
    clock and a random suffix, never from message content."""
    handler = MailboxHandler(inbox_dir)
    evil = _message(subject="../../../etc/passwd")
    path = handler._deliver(evil.as_bytes())
    assert os.path.dirname(os.path.abspath(path)) == os.path.abspath(inbox_dir)
    assert "passwd" not in os.path.basename(path)
