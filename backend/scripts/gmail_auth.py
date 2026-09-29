"""Connect the assistant to a Gmail inbox (one-time, and again every 7 days).

    python -m backend.scripts.gmail_auth
    python -m backend.scripts.gmail_auth --check     (test the saved token, no browser)
    python -m backend.scripts.gmail_auth --revoke    (disconnect and delete the token)

Opens a browser, asks you to sign in to Google and allow read-only access, then
saves a token to backend/secrets/gmail_token.json. The app reads that token;
there is no password anywhere.

Before the first run you need an OAuth client file from Google Cloud. The
README walks through it; in short: create a project, enable the Gmail API,
configure the consent screen as External / Testing with your address as a test
user, create an OAuth client ID of type "Desktop app", and save the downloaded
JSON as backend/secrets/gmail_client.json.

WHY IT MUST BE RUN BY A PERSON
------------------------------
Consent is the security boundary. The script cannot click "Allow" for you, and
nothing in this repository should try to: whoever runs it is deciding which
mailbox the app may read, and the Google page shows them exactly that.
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_ROOT, "backend", ".env"))

from backend.adapters.gmail_api_source import SCOPES  # noqa: E402
from backend.config import Config  # noqa: E402


def _profile(creds):
    """Which account and how much mail -- proof the token works."""
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False, static_discovery=True)
    return service.users().getProfile(userId="me").execute()


def _write_token(path, creds):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


def connect(config):
    from google_auth_oauthlib.flow import InstalledAppFlow

    client = config.gmail_client_file
    if not os.path.exists(client):
        print(f"No OAuth client file at:\n  {client}\n")
        print("Create one in Google Cloud Console:")
        print("  1. APIs & Services > Library > enable 'Gmail API'")
        print("  2. APIs & Services > OAuth consent screen > External, Testing,")
        print("     and add the Gmail address you will connect as a Test user")
        print("  3. APIs & Services > Credentials > Create credentials >")
        print("     OAuth client ID > Application type: Desktop app")
        print(f"  4. Download the JSON and save it as:\n     {client}")
        sys.exit(1)

    try:
        with open(client, encoding="utf-8") as handle:
            kind = next(iter(json.load(handle)), "")
    except (OSError, ValueError, StopIteration):
        sys.exit(f"{client} is not a valid OAuth client file. Download it again.")
    if kind != "installed":
        sys.exit(
            f"{client} is a '{kind}' client. It must be a 'Desktop app' OAuth client, "
            "or the browser sign-in cannot return to this script."
        )

    print("Opening a browser to sign in to Google.")
    print("If Google warns the app is unverified: Advanced > Go to (unsafe).")
    print("That warning is expected for an app in Testing that you created yourself.\n")

    flow = InstalledAppFlow.from_client_secrets_file(client, SCOPES)
    # prompt=consent guarantees a refresh token even if this Google account has
    # granted the app before; without one the app would stop after an hour.
    creds = flow.run_local_server(port=0, prompt="consent", open_browser=True)

    granted = set(creds.scopes or [])
    if not set(SCOPES) <= granted:
        sys.exit("Read access was not granted, so nothing was saved. Run again and tick the box.")

    _write_token(config.gmail_token_file, creds)
    profile = _profile(creds)
    print("Connected.")
    print(f"  account: {profile.get('emailAddress')}")
    print(f"  messages in mailbox: {profile.get('messagesTotal')}")
    print(f"  token saved to: {config.gmail_token_file}")
    print("")
    print("Set EMAIL_SOURCE=gmail in backend/.env if you have not, then restart:")
    print("  .\\start.ps1 -SkipInstall")
    print("")
    print("While the app is in Testing, Google ends this access after 7 days.")
    print("Run this script again when the inbox says so.")


def check(config):
    from backend.adapters.email_source import EmailSourceError
    from backend.adapters.gmail_api_source import _Credentials

    try:
        creds = _Credentials(config.gmail_token_file).get()
        profile = _profile(creds)
    except EmailSourceError as exc:
        sys.exit(str(exc))
    print("Gmail token is valid.")
    print(f"  account: {profile.get('emailAddress')}")
    print(f"  messages in mailbox: {profile.get('messagesTotal')}")


def revoke(config):
    import urllib.parse
    import urllib.request

    path = config.gmail_token_file
    if not os.path.exists(path):
        print("No saved token; nothing to disconnect.")
        return
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        token = data.get("refresh_token") or data.get("token")
        if token:
            body = urllib.parse.urlencode({"token": token}).encode()
            request = urllib.request.Request(
                "https://oauth2.googleapis.com/revoke", data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            urllib.request.urlopen(request, timeout=15)
            print("Access revoked with Google.")
    except Exception as exc:
        # Deleting the local token still disconnects this app; the grant can be
        # removed by hand at myaccount.google.com/permissions if revoking failed.
        print(f"Could not revoke with Google ({type(exc).__name__}). "
              "Remove it at https://myaccount.google.com/permissions if needed.")
    os.remove(path)
    print(f"Deleted {path}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Test the saved token without a browser.")
    group.add_argument("--revoke", action="store_true", help="Disconnect and delete the saved token.")
    args = parser.parse_args()

    config = Config(require_llm=False, require_auth=False)
    if args.check:
        check(config)
    elif args.revoke:
        revoke(config)
    else:
        connect(config)


if __name__ == "__main__":
    main()
