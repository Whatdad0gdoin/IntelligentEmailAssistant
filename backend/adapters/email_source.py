"""Email source adapter.

Routes never touch a mailbox directly. They ask an EmailSource for messages and
get back SourceEmail objects with every deterministic field already parsed from
headers (see headers.py).

Three sources are implemented.

FixtureEmailSource (EMAIL_SOURCE=fixture, the default) reads RFC-822 .eml files
from one or more configured directories -- the committed demo fixtures, plus the
directory the local mail server delivers into. That directory is the *mail
server's* role in the architecture, not application state -- the same position
an IMAP host would occupy. Nothing the app produces is ever written back to it,
which is what NFR-03 actually constrains.

GmailApiSource (gmail_api_source.py, EMAIL_SOURCE=gmail) reads a real Gmail
inbox over the Gmail API with OAuth, scoped to gmail.readonly. This is the
recommended way to read real mail: no password is stored, and read-only is
enforced by Google rather than only by how the adapter is written.

GmailImapSource (gmail_source.py, EMAIL_SOURCE=gmail_imap) reads the same inbox
over IMAP with an app password. Kept as a fallback because it needs no Google
Cloud project.

Adding each of the Gmail sources meant one new class returning SourceEmail
objects and one branch in the factory below -- no change to any route,
orchestrator module or view, which was the claim this file used to make in the
abstract and can now make from experience.
"""

import logging
import os
import threading
from email import policy
from email.parser import BytesParser

from backend.adapters.headers import message_id_of, parse_message

log = logging.getLogger(__name__)


class EmailSourceError(RuntimeError):
    """The mailbox could not be read. Distinct from 'the mailbox is empty'."""


class EmailSource:
    """Interface every source implements."""

    def list_emails(self):
        """Return all messages, newest first."""
        raise NotImplementedError

    def get_email(self, email_id):
        """Return one message by id, or None."""
        raise NotImplementedError


class FixtureEmailSource(EmailSource):
    """Reads .eml files from a directory.

    Files are re-read on each call rather than held in a long-lived cache. That
    is deliberate: it keeps request handling stateless (section 1) and means no
    message body outlives the request that needed it.
    """

    def __init__(self, directory, extra_dirs=()):
        # `directory` must exist; a missing one is a misconfiguration worth an
        # error. The extras are optional -- the delivery directory legitimately
        # does not exist until the first message arrives.
        self.directory = directory
        self.extra_dirs = tuple(extra_dirs)

    def _files(self):
        """(directory, filename) for every .eml across all configured dirs."""
        if not os.path.isdir(self.directory):
            raise EmailSourceError(
                f"Email fixture directory not found: {self.directory}. "
                f"Set EMAIL_FIXTURE_DIR or create the directory."
            )
        found = []
        for directory in (self.directory,) + self.extra_dirs:
            if not os.path.isdir(directory):
                continue
            for name in sorted(os.listdir(directory)):
                if name.lower().endswith(".eml"):
                    found.append((directory, name))
        return found

    def _read_all(self):
        emails = []
        parser = BytesParser(policy=policy.default)
        for directory, name in self._files():
            path = os.path.join(directory, name)
            try:
                with open(path, "rb") as handle:
                    message = parser.parse(handle)
            except OSError as exc:
                # Log the filename, never the contents.
                log.warning("Skipping unreadable message file %s: %s", name, exc.strerror)
                continue
            emails.append(parse_message(message))
        # Newest first. An unparseable Date sorts last rather than crashing.
        emails.sort(key=lambda e: e.received_at or "", reverse=True)
        return emails

    def list_emails(self):
        return self._read_all()

    def get_email(self, email_id):
        """Locate one message by id, parsing bodies for at most one file.

        A first pass reads headers only, which is enough to compute the id
        (see headers.message_id_of). Only the matching file is then parsed in
        full. This is still stateless: nothing is retained between calls, and
        no body is decoded except the one being returned.
        """
        parser = BytesParser(policy=policy.default)
        for directory, name in self._files():
            path = os.path.join(directory, name)
            try:
                with open(path, "rb") as handle:
                    headers = parser.parse(handle, headersonly=True)
                if message_id_of(headers) != email_id:
                    continue
                with open(path, "rb") as handle:
                    return parse_message(parser.parse(handle))
            except OSError as exc:
                log.warning("Skipping unreadable message file %s: %s", name, exc.strerror)
        return None


_lock = threading.Lock()
_sources = {}

# fixture   - .eml files on disk (the default; what the tests use)
# gmail     - a real Gmail inbox over the Gmail API with OAuth (recommended)
# gmail_imap - the same inbox over IMAP with an app password (fallback)
SOURCES = ("fixture", "gmail", "gmail_imap")


def _source_key(config):
    """Identity of the configured source: same settings, same instance.

    The key carries the settings rather than just the name so a test that
    repoints a directory, or a config that switches mailbox, gets its own
    instance instead of one built for the previous settings. The password is
    not part of it -- it is not an identity, and keys end up in tracebacks.
    """
    if config.email_source == "gmail":
        return ("gmail", config.gmail_token_file, config.gmail_mailbox, config.gmail_limit)
    if config.email_source == "gmail_imap":
        return ("gmail_imap", config.gmail_host, config.gmail_port,
                config.gmail_user, config.gmail_mailbox)
    return ("fixture", config.email_fixture_dir, config.email_inbox_dir)


def get_email_source(config):
    """Return the configured source. One instance per configuration, reused."""
    if config.email_source not in SOURCES:
        raise EmailSourceError(
            f"Unknown EMAIL_SOURCE '{config.email_source}'. "
            f"This build implements: {', '.join(SOURCES)}."
        )
    key = _source_key(config)
    with _lock:
        if key not in _sources:
            if config.email_source == "gmail":
                # Imported here, not at module scope: both Gmail adapters import
                # this module for the EmailSource base class, and a fixture-only
                # deployment has no reason to load a Google client at all.
                from backend.adapters.gmail_api_source import GmailApiSource

                _sources[key] = GmailApiSource(
                    token_path=config.gmail_token_file,
                    label=config.gmail_mailbox,
                    limit=config.gmail_limit,
                    timeout=config.gmail_timeout,
                )
            elif config.email_source == "gmail_imap":
                from backend.adapters.gmail_source import GmailImapSource

                _sources[key] = GmailImapSource(
                    host=config.gmail_host,
                    port=config.gmail_port,
                    username=config.gmail_user,
                    password=config.gmail_app_password,
                    mailbox=config.gmail_mailbox,
                    limit=config.gmail_limit,
                    timeout=config.gmail_timeout,
                )
            else:
                _sources[key] = FixtureEmailSource(
                    config.email_fixture_dir, extra_dirs=(config.email_inbox_dir,)
                )
        return _sources[key]


def set_email_source(config, source):
    """Test seam: point the configured key at a supplied source."""
    with _lock:
        _sources[_source_key(config)] = source
