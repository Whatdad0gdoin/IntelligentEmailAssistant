"""Connect a user's own Gmail from Settings (FR-08, NFR-04).

GET  /api/gmail             ->  { available, connected, address, connected_at }
POST /api/gmail/connect     ->  { auth_url }: the page opens it in a popup
GET  /api/gmail/callback    ->  HTML. Google sends the popup back here. Public.
POST /api/gmail/disconnect  ->  { connected: false, revoked }

This is the same OAuth grant the gmail_auth script makes for the server's own
mailbox, as a web flow for every signed-in user: one gmail.readonly token per
user, encrypted in the accounts database (backend/accounts.py). Until a user
connects, they see the demo mailbox.

WHY A POPUP
-----------
The login token lives only in memory (section 5.1). Sending the whole page to
Google would end the session on the way back, so Google's consent page opens
in a popup, the app keeps running, and Settings learns the result by asking
GET /api/gmail.

WHY THE CALLBACK IS PUBLIC, AND WHAT PROTECTS IT
------------------------------------------------
The popup arrives from Google with no Authorization header. The user is found
from `state` instead: a random value made by POST /connect, kept only on the
server, single-use and valid for ten minutes. On its own that would allow a
classic attack: someone starts a connection on their own account and sends
the Google link to a victim, whose Gmail would then be attached to the
attacker's account. So /connect also sets a cookie in the browser that asked,
and the callback refuses any `state` that arrives without it.

PKCE: the code verifier also stays on the server, never in the URL.

GOOGLE'S LIMITS
---------------
gmail.readonly is a restricted scope. While the Google app is in Testing, only
addresses added as test users in Google Cloud can connect (at most 100), and
Google ends each connection 7 days after consent. The callback explains the
first when Google refuses, and the inbox explains the second when it happens.
"""

import hmac
import html
import json
import logging
import os
import secrets
import threading
import time

from flask import Blueprint, jsonify, make_response, request

from backend.accounts import connected_gmail, decrypt_token, encrypt_token, get_store
from backend.adapters.email_source import forget_user_source
from backend.adapters.gmail_api_source import SCOPES
from backend.orchestrator import cache
from backend.routes.support import config, current_user

log = logging.getLogger(__name__)

bp = Blueprint("gmail", __name__, url_prefix="/api/gmail")

_COOKIE = "mk_gmail_flow"
_FLOW_SECONDS = 600
_MAX_PENDING = 500

# state -> (user, code_verifier, browser nonce, expiry). In memory, like the
# summary cache: a restart mid-connection just means pressing Connect again.
_pending = {}
_pending_lock = threading.Lock()


def _remember(state, entry):
    now = time.monotonic()
    with _pending_lock:
        for key in [k for k, v in _pending.items() if v[3] < now]:
            del _pending[key]
        while len(_pending) >= _MAX_PENDING:
            del _pending[next(iter(_pending))]
        _pending[state] = entry


def _take(state):
    """The pending connection for this state, once. None if unknown or expired."""
    with _pending_lock:
        entry = _pending.pop(state, None)
    if entry is None or entry[3] < time.monotonic():
        return None
    return entry


def _client_config(settings):
    """The web OAuth client from Google Cloud, or None if it is not set up."""
    path = settings.gmail_web_client_file
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        log.warning("gmail connect: the web client file is unreadable")
        return None
    client = data.get("web") or data.get("installed") if isinstance(data, dict) else None
    if not isinstance(client, dict) or not client.get("client_id"):
        return None
    return data


def _flow(settings, client_config, verifier):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=settings.gmail_redirect_uri,
        code_verifier=verifier,
        autogenerate_code_verifier=False,
    )


def exchange_code(settings, client_config, code, verifier):
    """Trade Google's one-time code for a token. Returns (credentials, granted scopes).

    A module-level function so the tests can stand in for Google.
    """
    # Google's consent screen lets the user untick a permission, and the token
    # then comes back with fewer scopes than were asked for. oauthlib treats
    # that as an exception unless relaxed; the scopes are checked below instead,
    # where the user can be told what to do about it.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = _flow(settings, client_config, verifier)
    token = flow.fetch_token(code=code)
    scope = token.get("scope") or []
    granted = set(scope.split() if isinstance(scope, str) else scope)
    return flow.credentials, granted


def gmail_address(creds):
    """Which Gmail account was connected. gmail.readonly covers this call."""
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False, static_discovery=True)
    return service.users().getProfile(userId="me").execute()["emailAddress"]


def revoke(token):
    """Ask Google to end the grant. Best effort: the local copy goes regardless."""
    import requests

    try:
        response = requests.post(
            "https://oauth2.googleapis.com/revoke", data={"token": token}, timeout=10
        )
        return response.status_code == 200
    except requests.RequestException as exc:
        log.warning("gmail disconnect: revoke failed (%s)", type(exc).__name__)
        return False


def _status(settings, user):
    connection = connected_gmail(settings, user)
    return {
        "available": _client_config(settings) is not None,
        "connected": connection is not None,
        "address": connection["address"] if connection else None,
        "connected_at": connection["connected_at"] if connection else None,
    }


def _mailbox_changed(user):
    """The next request reads the new mailbox, and nothing cached from the old
    one (labels, summaries) is shown against it."""
    forget_user_source(user)
    cache.clear_all(user)


@bp.get("")
def status():
    return jsonify(_status(config(), current_user())), 200


@bp.post("/connect")
def connect():
    settings = config()
    client_config = _client_config(settings)
    if client_config is None:
        return jsonify({
            "error": "Connecting Gmail is not set up on this server yet. The README "
                     "explains the Google Cloud step (Let users connect their own Gmail)."
        }), 503

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    browser = secrets.token_urlsafe(32)
    auth_url, _ = _flow(settings, client_config, verifier).authorization_url(
        access_type="offline",
        # Always show the consent screen, so Google always returns a refresh
        # token, including for someone reconnecting after the 7-day expiry.
        prompt="consent",
        state=state,
    )
    _remember(state, (current_user(), verifier, browser, time.monotonic() + _FLOW_SECONDS))

    response = jsonify({"auth_url": auth_url})
    response.set_cookie(
        _COOKIE, browser, max_age=_FLOW_SECONDS, path="/api/gmail",
        httponly=True, samesite="Lax", secure=request.is_secure,
    )
    return response, 200


@bp.post("/disconnect")
def disconnect():
    settings = config()
    user = current_user()
    store = get_store(settings)
    revoked = False
    row = store.gmail_connection(user)
    if row:
        try:
            data = json.loads(decrypt_token(settings, row["token"]) or "{}")
        except ValueError:
            data = {}
        token = data.get("refresh_token") or data.get("token")
        if token:
            revoked = revoke(token)
    store.delete_gmail(user)
    _mailbox_changed(user)
    return jsonify({"connected": False, "revoked": revoked}), 200


@bp.get("/callback")
def callback():
    settings = config()
    entry = _take(request.args.get("state", ""))
    if entry is None:
        return _page(400, "This link has expired",
                     "Go back to Settings and press Connect Gmail again.")
    user, verifier, browser, _ = entry

    if not hmac.compare_digest(request.cookies.get(_COOKIE, ""), browser):
        return _page(400, "This sign-in did not start here",
                     "Connect Gmail from Settings in this browser, and finish in the window it opens.")

    if request.args.get("error"):
        # access_denied: the user pressed Cancel, or Google blocked an address
        # that is not a test user. Google's own page has already said which.
        return _page(403, "Gmail was not connected",
                     "Google did not allow the connection. While MailKit is in testing, only "
                     "Gmail addresses the team has added as test users can connect. If yours "
                     "should be one, ask the team to add it.")

    code = request.args.get("code")
    client_config = _client_config(settings)
    if not code or client_config is None:
        return _page(400, "Gmail was not connected",
                     "Google did not send a sign-in code back. Try Connect Gmail again.")

    try:
        creds, granted = exchange_code(settings, client_config, code, verifier)
    except Exception as exc:  # noqa: BLE001 -- any failure here means "try again"
        log.warning("gmail connect: code exchange failed (%s)", type(exc).__name__)
        return _page(502, "Gmail was not connected",
                     "Google did not accept the sign-in. Try Connect Gmail again.")

    if not set(SCOPES) <= granted:
        return _page(403, "MailKit needs to read your email",
                     "On Google's page, tick the box that lets MailKit view your email "
                     "messages, then try again. Access is read-only: MailKit cannot send, "
                     "delete or change anything.")

    try:
        address = gmail_address(creds)
    except Exception as exc:  # noqa: BLE001
        log.warning("gmail connect: profile lookup failed (%s)", type(exc).__name__)
        return _page(502, "Gmail was not connected",
                     "Connected to Google, but Gmail did not answer. Try again in a minute.")

    get_store(settings).save_gmail(user, address, encrypt_token(settings, creds.to_json()))
    _mailbox_changed(user)
    log.info("gmail connect: a user connected their mailbox")

    response = _page(200, "Gmail connected",
                     f"MailKit can now read {address}. This window will close; "
                     "your inbox reloads on its own.", ok=True)
    response.delete_cookie(_COOKIE, path="/api/gmail")
    return response


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MailKit: {title}</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: #f4f6fb; color: #0f172a;
         font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 420px; margin: 16px; padding: 28px 30px; background: #fff;
         border: 1px solid #e2e8f0; border-radius: 16px; }}
  h1 {{ margin: 0 0 8px; font-size: 20px; }}
  p {{ margin: 0 0 10px; color: #475569; }}
  .ok {{ color: #15803d; }}
  .small {{ font-size: 13px; color: #94a3b8; }}
</style>
</head>
<body>
<main>
  <h1 class="{cls}">{title}</h1>
  <p>{detail}</p>
  <p class="small">You can close this window.</p>
</main>
<script>
  var result = {result};
  try {{ new BroadcastChannel("mailkit-gmail").postMessage(result); }} catch (e) {{}}
  if (result.ok) setTimeout(function () {{ window.close(); }}, 1500);
</script>
</body>
</html>
"""


def _page(status_code, title, detail, ok=False):
    """The small page the popup shows. Also tells Settings, when the browser
    allows it, so the result appears without waiting for the next check."""
    result = json.dumps({"ok": ok, "title": title, "detail": detail}).replace("<", "\\u003c")
    body = _PAGE.format(
        title=html.escape(title), detail=html.escape(detail),
        cls="ok" if ok else "", result=result,
    )
    response = make_response(body, status_code)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    # The address bar holds Google's one-time code; no page this links to
    # needs to see it.
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"
    )
    return response
