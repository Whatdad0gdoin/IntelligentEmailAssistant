"""Send a test email to the local mail server.

    python tools/send_test_email.py
    python tools/send_test_email.py --category studies
    python tools/send_test_email.py --interactive

WHY THIS LIVES OUTSIDE backend/
-------------------------------
It imports smtplib, and tests/test_draft.py asserts that no mail-sending
library appears anywhere under backend/. That test is the guarantee behind
FR-03: a send path cannot exist if nothing in the backend can send mail. This
script sends *to* the local receiver so inbound delivery can be tested, which
is the opposite direction, but the guard is deliberately blunt and weakening it
to admit a convenience script would be a bad trade. So the script moved
instead.

This speaks real SMTP to backend/mailserver.py, so it exercises the same path a
mail client would. It exists because the alternative -- configuring Thunderbird
against localhost:2525 -- is a lot of setup just to check the pipe works.

The presets are worded to land in different categories, which makes it easy to
watch FR-02 sort live rather than trusting the fixtures.
"""

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_ROOT, "backend", ".env"))

from backend.config import Config  # noqa: E402

PRESETS = {
    "work": (
        "Andrea Lawson <a.lawson@northgate.com.au>",
        "Budget sign-off needed before Thursday",
        "Hi,\n\n"
        "The Q3 budget needs your sign-off before the board pack goes out on "
        "Thursday. I have attached nothing yet - the figures are still with "
        "finance - but I wanted to flag the date now.\n\n"
        "Could you confirm you will have time on Wednesday to review it?\n\n"
        "Thanks,\nAndrea",
    ),
    "studies": (
        "Dr Helen Marsh <h.marsh@monash.edu>",
        "FIT3164 progress meeting moved to Tuesday",
        "Hi,\n\n"
        "I need to move our progress meeting from Monday to Tuesday at 11am, "
        "room 9.15. Please bring the updated evaluation results and the draft "
        "of section 4.\n\n"
        "If Tuesday does not work, let me know and we will find another slot.\n\n"
        "Regards,\nHelen",
    ),
    "personal": (
        "Tom Whitaker <tom.whitaker.mel@gmail.com>",
        "Still on for Saturday?",
        "Hey,\n\n"
        "Just checking you are still coming Saturday. We were thinking of "
        "eating around 7 rather than 8, if that suits.\n\n"
        "Let me know either way.\n\nTom",
    ),
    "promotions": (
        "Gearline <deals@gearline-mail.com>",
        "48 hours only: 40% off everything",
        "Our end of season sale is live.\n\n"
        "40% off the entire range for the next 48 hours. No code needed, the "
        "discount applies at checkout.\n\n"
        "Shop now. Unsubscribe | Manage preferences",
    ),
}


def build_message(sender, to, subject, body):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=sorted(PRESETS), default="work",
                        help="Which preset to send (default: work).")
    parser.add_argument("--from", dest="sender", help="Override the From header.")
    parser.add_argument("--subject", help="Override the subject.")
    parser.add_argument("--body", help="Override the body.")
    parser.add_argument("--to", default="you@mailkit.local", help="Recipient header.")
    parser.add_argument("--host", help="Override SMTP_HOST.")
    parser.add_argument("--port", type=int, help="Override SMTP_PORT.")
    parser.add_argument("--interactive", action="store_true",
                        help="Type your own subject and body.")
    args = parser.parse_args()

    config = Config(require_llm=False, require_auth=False)
    host = args.host or config.smtp_host
    port = args.port or config.smtp_port

    sender, subject, body = PRESETS[args.category]

    if args.interactive:
        sender = input(f"From [{sender}]: ").strip() or sender
        subject = input("Subject: ").strip() or subject
        print("Body (finish with a blank line):")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line.strip() and lines:
                break
            lines.append(line)
        body = "\n".join(lines) or body

    sender = args.sender or sender
    subject = args.subject or subject
    body = args.body or body

    message = build_message(sender, args.to, subject, body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.send_message(message)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"Could not reach the mail server at {host}:{port} ({exc}).")
        print("Start it first:  python -m backend.mailserver")
        sys.exit(1)

    print(f"Sent to {host}:{port}")
    print(f"  From:    {sender}")
    print(f"  Subject: {subject}")
    print("")
    print("Open the app and reload the inbox to see it.")


if __name__ == "__main__":
    main()
