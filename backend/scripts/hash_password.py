"""Generate a password hash for AUTH_USERS.

    python -m backend.scripts.hash_password

Prompts for an email and password (password is not echoed) and prints a JSON
fragment to paste into the AUTH_USERS environment variable.
"""

import getpass
import json

from werkzeug.security import generate_password_hash


def main():
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match.")
    if not email or not password:
        raise SystemExit("Email and password are both required.")
    print("\nAdd this to AUTH_USERS (merge with any existing entries):\n")
    print(json.dumps({email: generate_password_hash(password)}))


if __name__ == "__main__":
    main()
