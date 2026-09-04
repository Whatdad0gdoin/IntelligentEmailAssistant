"""Add or update a login account in backend/.env.

    python -m backend.scripts.add_user james@monash.edu hunter2
    python -m backend.scripts.add_user kevin@monash.edu          (prompts, hidden)
    python -m backend.scripts.add_user --list

Writes the account straight into AUTH_USERS. The previous helper only printed a
JSON fragment for you to merge by hand, which meant editing a long single line
and, more than once, ending up with a file that would not parse.

You still choose the password and you still know it -- it is the argument you
typed. What is stored is a one-way hash of it, so the file cannot hand your
password to anyone who reads it. That is what NFR-04 is graded on, and it costs
nothing here: nothing about hashing stops you logging in with a password you
picked.
"""

import argparse
import getpass
import json
import os
import re
import sys

from werkzeug.security import generate_password_hash

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
_LINE = re.compile(r"(?m)^AUTH_USERS=.*$")


def _load():
    if not os.path.exists(ENV_PATH):
        raise SystemExit(
            f"{ENV_PATH} does not exist yet.\n"
            "Run .\\start.ps1 once to create it from the example."
        )
    text = open(ENV_PATH, encoding="utf-8").read()
    match = _LINE.search(text)
    if not match:
        return text, {}
    raw = match.group(0).split("=", 1)[1].strip()
    try:
        users = json.loads(raw or "{}")
    except json.JSONDecodeError:
        raise SystemExit(
            "AUTH_USERS in backend/.env is not valid JSON, so it cannot be edited "
            "safely. Fix or clear that line first."
        )
    return text, users


def _save(text, users):
    line = "AUTH_USERS=" + json.dumps(users, separators=(", ", ": "))
    updated = _LINE.sub(lambda _: line, text) if _LINE.search(text) else text.rstrip() + "\n" + line + "\n"
    # Write via a temporary file: a half-written .env would take the app down
    # on its next start, and this file is not in version control.
    temp = ENV_PATH + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(updated)
    os.replace(temp, ENV_PATH)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", nargs="?", help="Account email address.")
    parser.add_argument("password", nargs="?", help="Password. Omit to be prompted without echo.")
    parser.add_argument("--list", action="store_true", help="Show configured accounts.")
    parser.add_argument("--remove", metavar="EMAIL", help="Delete an account.")
    args = parser.parse_args()

    text, users = _load()

    if args.list:
        if not users:
            print("No accounts configured.")
            return
        print(f"{len(users)} account(s) in backend/.env:")
        for email in sorted(users):
            print(f"  {email}")
        return

    if args.remove:
        email = args.remove.strip().lower()
        if email not in users:
            raise SystemExit(f"No account for {email}.")
        if len(users) == 1:
            raise SystemExit(
                f"{email} is the only account. Removing it would lock you out; "
                "add another first."
            )
        del users[email]
        _save(text, users)
        print(f"Removed {email}. Restart the backend to apply.")
        return

    if not args.email:
        parser.print_help()
        sys.exit(1)

    email = args.email.strip().lower()
    if "@" not in email:
        raise SystemExit(f"{email!r} does not look like an email address.")

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
    if not password:
        raise SystemExit("A password is required.")

    existed = email in users
    users[email] = generate_password_hash(password)
    _save(text, users)

    print(f"{'Updated' if existed else 'Added'} {email}.")
    print("")
    print("  Sign in with:")
    print(f"    {email}")
    print(f"    {password}")
    print("")
    print("  Restart the backend to apply:  .\\start.ps1 -SkipInstall")


if __name__ == "__main__":
    main()
