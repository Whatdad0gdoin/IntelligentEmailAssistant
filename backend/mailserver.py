"""Local SMTP server: send a real email to the assistant and read it in the app.

    python -m backend.mailserver

Listens on SMTP, writes each accepted message into the delivery directory as a
.eml file, and stops. The Flask API picks it up on the next /api/inbox because
FixtureEmailSource re-reads its directories on every call.

WHY THIS IS A SEPARATE PROCESS, AND WHY THAT MATTERS FOR NFR-03
---------------------------------------------------------------
NFR-03 says the *assistant* does not persist email content. This program does
persist it -- that is the entire job of a mail server, and a mailbox that
forgot your mail would not be a mailbox.

The two are different tiers. This process stands in for the mail provider that
would hold the user's mailbox; the Flask API remains a stateless reader of it
and still writes nothing. Keeping them as separate processes is what makes that
claim checkable rather than rhetorical: `backend/app.py` and every route,
orchestrator and adapter module import nothing from this file, and
tests/test_mailserver.py asserts that.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No authentication, no TLS, no relaying. It accepts mail and writes it to a
directory. Binding it to a public interface would make it an open relay
candidate, so the default host is 127.0.0.1 and the LAN option is opt-in and
documented. This is a development tool, not a mail host.
"""

import argparse
import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import formatdate, make_msgid

from aiosmtpd.controller import Controller
from dotenv import load_dotenv

# Same settings file the API reads, so SMTP_PORT and EMAIL_INBOX_DIR can be
# configured in one place.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from backend.config import Config  # noqa: E402

log = logging.getLogger("mailserver")

# Filenames are derived from the arrival time, never from the subject: a
# subject can contain path separators, and a filename is the one place email
# content would leak into something a human reads out of context.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class MailboxHandler:
    """Writes each accepted message into `directory`."""

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    async def handle_DATA(self, server, session, envelope):
        try:
            path = self._deliver(envelope.content)
        except OSError as exc:
            # Never echo the message back in an error: SMTP responses are logged
            # by the sending client too.
            log.error("Delivery failed: %s", exc.strerror or "write error")
            return "451 Local delivery failed"

        message = BytesParser(policy=policy.default).parsebytes(envelope.content)
        # Sender and subject only. The body is never logged (NFR-03).
        log.info(
            "Delivered from=%s subject=%r -> %s",
            envelope.mail_from,
            (message.get("Subject") or "(no subject)")[:120],
            os.path.basename(path),
        )
        return "250 Message accepted for delivery"

    def _deliver(self, raw):
        message = BytesParser(policy=policy.default).parsebytes(raw)

        # A Message-ID must exist and must be unique. Without one, headers.py
        # derives a stable id from From|Subject|Date -- so sending the same test
        # email twice would produce two files that the app treats as one
        # message, and the second would silently never appear.
        if not (message.get("Message-ID") or "").strip():
            message["Message-ID"] = make_msgid(domain="mailkit.local")

        # Some minimal clients omit Date. The inbox sorts on it, so a missing
        # one would sort the newest message to the bottom.
        if not (message.get("Date") or "").strip():
            message["Date"] = formatdate(localtime=True)

        # Mail that just arrived is unread. The fixture format carries read
        # state as X-Unread (see headers.py); an IMAP adapter would map the
        # server-side flag onto the same field.
        if not (message.get("X-Unread") or "").strip():
            message["X-Unread"] = "1"

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        name = _UNSAFE.sub("_", f"received-{stamp}-{uuid.uuid4().hex[:8]}.eml")
        path = os.path.join(self.directory, name)

        # Write to a temporary name and rename into place. The API may read the
        # directory at any moment, and a half-written file would parse as a
        # corrupt message rather than simply not being there yet.
        temp = path + ".part"
        with open(temp, "wb") as handle:
            handle.write(message.as_bytes(policy=policy.SMTP))
        os.replace(temp, path)
        return path


def build_controller(config, directory=None):
    """Construct the SMTP controller without starting it (used by tests)."""
    return Controller(
        MailboxHandler(directory or config.email_inbox_dir),
        hostname=config.smtp_host,
        port=config.smtp_port,
        data_size_limit=config.smtp_max_bytes,
    )


def main():
    parser = argparse.ArgumentParser(description="Local SMTP receiver for the assistant.")
    parser.add_argument("--host", help="Override SMTP_HOST. Use 0.0.0.0 to accept from other devices.")
    parser.add_argument("--port", type=int, help="Override SMTP_PORT.")
    args = parser.parse_args()

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(message)s")

    # No LLM and no auth: this tier signs nothing and calls no model.
    config = Config(require_llm=False, require_auth=False)
    if args.host:
        config.smtp_host = args.host
    if args.port:
        config.smtp_port = args.port

    controller = build_controller(config)
    controller.start()

    print("")
    print(f"  Mail server listening on {config.smtp_host}:{config.smtp_port}")
    print(f"  Delivering to {config.email_inbox_dir}")
    print("")
    print("  Send a test message with:")
    print("      python tools/send_test_email.py")
    print("")
    if config.smtp_host in ("127.0.0.1", "localhost"):
        print("  Only this machine can send to it. To send from a phone or another")
        print("  computer on the same network, restart with:")
        print("      python -m backend.mailserver --host 0.0.0.0")
        print("")
    print("  Then open the app and reload the inbox. Ctrl+C to stop.")
    print("")

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        print("Mail server stopped.")


if __name__ == "__main__":
    main()
