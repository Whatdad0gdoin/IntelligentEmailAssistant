"""Check the Gmail connection before pointing the app at it.

    python tools/check_gmail.py

Reads backend/.env, connects exactly the way GmailImapSource does, and prints
what it can see. It exists because every setup failure here looks identical
from the browser -- an empty inbox with a red banner -- while the actual causes
(2-step verification off, account password used instead of an app password,
IMAP disabled in Gmail's settings, a label that does not exist, a network that
blocks 993) each need a different fix and are distinguishable at the point of
connection.

Sender and subject of the newest few messages are printed, because "it
connected" is not the same claim as "it is reading the mailbox I meant". Bodies
are never printed.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_ROOT, "backend", ".env"))

from backend.adapters.email_source import EmailSourceError  # noqa: E402
from backend.adapters.gmail_source import GmailImapSource  # noqa: E402
from backend.config import Config, ConfigError  # noqa: E402

PREVIEW = 5


def main():
    try:
        config = Config(require_llm=False, require_auth=False)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 2

    if not config.gmail_user or not config.gmail_app_password:
        print("GMAIL_USER and GMAIL_APP_PASSWORD are not both set in backend/.env.")
        print("")
        print("  1. Switch on 2-step verification:  https://myaccount.google.com/security")
        print("  2. Create an app password:         https://myaccount.google.com/apppasswords")
        print("  3. Put it in backend/.env as GMAIL_APP_PASSWORD (spaces are fine to strip)")
        return 2

    source = GmailImapSource(
        host=config.gmail_host,
        port=config.gmail_port,
        username=config.gmail_user,
        password=config.gmail_app_password,
        mailbox=config.gmail_mailbox,
        limit=config.gmail_limit,
        timeout=config.gmail_timeout,
    )

    print(f"Connecting to {config.gmail_host}:{config.gmail_port} as {config.gmail_user}")
    print(f"Mailbox {config.gmail_mailbox!r}, newest {config.gmail_limit}")
    print("")

    try:
        emails = source.list_emails()
    except EmailSourceError as exc:
        print(f"FAILED: {exc}")
        print("")
        print("If the credentials are right, check that IMAP is enabled:")
        print("  Gmail -> Settings -> Forwarding and POP/IMAP -> Enable IMAP")
        return 1

    if not emails:
        print("Connected, but the mailbox is empty.")
        print("Send yourself a message, or set GMAIL_MAILBOX to a label that has mail in it.")
        return 0

    unread = sum(1 for e in emails if e.unread)
    print(f"OK: {len(emails)} message(s), {unread} unread.")
    print("")
    for email in emails[:PREVIEW]:
        mark = "*" if email.unread else " "
        print(f"  {mark} {(email.sender_name or email.sender)[:28]:28}  {email.subject[:52]}")
    if len(emails) > PREVIEW:
        print(f"    ... and {len(emails) - PREVIEW} more")

    print("")
    print("Set EMAIL_SOURCE=gmail in backend/.env and restart the backend to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
