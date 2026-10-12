"""Connect Gmail from Settings (routes/gmail.py, accounts.UserTokenStore).

Google is stood in for at the two module-level seams, exchange_code and
gmail_address; everything else is the production code: state handling, the
browser cookie, the encrypted store, and which mailbox each user is served.
"""

import copy
import json
from urllib.parse import parse_qs, urlparse

import pytest

from backend.accounts import UserTokenStore, connected_gmail, get_store
from backend.adapters.email_source import (
    EmailSourceError,
    FixtureEmailSource,
    get_email_source,
    mailbox_of,
)
from backend.adapters.gmail_api_source import SCOPES, GmailApiSource
from backend.routes import gmail as gmail_routes
from tests.conftest import TEST_EMAIL

REFRESH = "1//secret-refresh-token"
ADDRESS = "someone@gmail.com"


class FakeCreds:
    def to_json(self):
        return json.dumps({
            "token": "access-token", "refresh_token": REFRESH,
            "client_id": "test-client", "client_secret": "s",
            "token_uri": "https://oauth2.googleapis.com/token", "scopes": SCOPES,
        })


@pytest.fixture
def web_client(config, tmp_path):
    path = tmp_path / "gmail_web_client.json"
    path.write_text(json.dumps({"web": {
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [config.gmail_redirect_uri],
    }}), encoding="utf-8")
    config.gmail_web_client_file = str(path)
    return path


@pytest.fixture
def google(monkeypatch):
    """Google answering: a token with read access, for ADDRESS."""
    calls = {"exchange": [], "revoke": []}

    def exchange(settings, client_config, code, verifier):
        calls["exchange"].append({"code": code, "verifier": verifier})
        return FakeCreds(), set(SCOPES)

    monkeypatch.setattr(gmail_routes, "exchange_code", exchange)
    monkeypatch.setattr(gmail_routes, "gmail_address", lambda creds: ADDRESS)
    monkeypatch.setattr(gmail_routes, "revoke", lambda token: calls["revoke"].append(token) or True)
    return calls


def _start(client, auth_headers):
    response = client.post("/api/gmail/connect", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    query = parse_qs(urlparse(response.get_json()["auth_url"]).query)
    return response, query


def _finish(client, state, **params):
    return client.get("/api/gmail/callback", query_string={"state": state, "code": "4/code", **params})


def _connect(client, auth_headers):
    _, query = _start(client, auth_headers)
    response = _finish(client, query["state"][0])
    assert response.status_code == 200, response.get_data(as_text=True)
    return response


# --- status and starting --------------------------------------------------------------


def test_without_a_web_client_connecting_is_unavailable(client, auth_headers):
    status = client.get("/api/gmail", headers=auth_headers).get_json()
    assert status == {"available": False, "connected": False, "address": None, "connected_at": None}
    response = client.post("/api/gmail/connect", headers=auth_headers)
    assert response.status_code == 503
    assert "README" in response.get_json()["error"]


def test_with_a_web_client_connecting_is_available(web_client, client, auth_headers):
    assert client.get("/api/gmail", headers=auth_headers).get_json()["available"] is True


def test_connect_asks_google_for_read_only_access_with_pkce(web_client, client, auth_headers, config):
    response, query = _start(client, auth_headers)
    url = urlparse(response.get_json()["auth_url"])

    assert url.netloc == "accounts.google.com"
    assert query["client_id"] == ["test-client.apps.googleusercontent.com"]
    assert query["redirect_uri"] == [config.gmail_redirect_uri]
    assert query["scope"] == SCOPES
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["state"][0]) >= 32
    # The verifier stays on the server: only its hash travels.
    verifier = gmail_routes._pending[query["state"][0]][1]
    assert verifier not in response.get_json()["auth_url"]


def test_connect_sets_an_http_only_cookie_for_the_callback(web_client, client, auth_headers):
    response, _ = _start(client, auth_headers)
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith("mk_gmail_flow=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=/api/gmail" in cookie


# --- the callback ---------------------------------------------------------------------


def test_a_successful_callback_connects_the_user_who_started(web_client, google, client, auth_headers, config):
    response = _connect(client, auth_headers)
    page = response.get_data(as_text=True)
    assert "Gmail connected" in page and ADDRESS in page
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"

    status = client.get("/api/gmail", headers=auth_headers).get_json()
    assert status["connected"] is True and status["address"] == ADDRESS
    assert connected_gmail(config, TEST_EMAIL)["address"] == ADDRESS


def test_the_exchange_uses_the_verifier_made_at_connect(web_client, google, client, auth_headers):
    _, query = _start(client, auth_headers)
    verifier = gmail_routes._pending[query["state"][0]][1]
    _finish(client, query["state"][0])
    assert google["exchange"] == [{"code": "4/code", "verifier": verifier}]


def test_the_stored_token_is_encrypted(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    raw = open(config.accounts_db, "rb").read()
    assert REFRESH.encode() not in raw
    assert b"access-token" not in raw
    assert json.loads(UserTokenStore(config, TEST_EMAIL).load())["refresh_token"] == REFRESH


def test_a_state_works_once(web_client, google, client, auth_headers):
    _, query = _start(client, auth_headers)
    assert _finish(client, query["state"][0]).status_code == 200
    again = _finish(client, query["state"][0])
    assert again.status_code == 400
    assert "expired" in again.get_data(as_text=True)


def test_an_unknown_state_is_refused(web_client, google, client):
    response = _finish(client, "made-up")
    assert response.status_code == 400
    assert google["exchange"] == []


def test_an_expired_state_is_refused(web_client, google, client):
    gmail_routes._remember("old-state", (TEST_EMAIL, "verifier", "browser", 0))
    client.set_cookie("mk_gmail_flow", "browser", path="/api/gmail")
    assert _finish(client, "old-state").status_code == 400
    assert google["exchange"] == []


def test_a_link_finished_in_another_browser_is_refused(web_client, google, app, client, auth_headers, config):
    """Someone starts a connection on their own account and sends the Google
    link to a victim. The victim's browser has no cookie from /connect, so
    the victim's Gmail is not attached to the attacker's account."""
    _, query = _start(client, auth_headers)
    victim = app.test_client()
    response = _finish(victim, query["state"][0])
    assert response.status_code == 400
    assert "did not start here" in response.get_data(as_text=True)
    assert google["exchange"] == []
    assert connected_gmail(config, TEST_EMAIL) is None


def test_access_denied_explains_the_test_user_list(web_client, google, client, auth_headers):
    _, query = _start(client, auth_headers)
    response = client.get("/api/gmail/callback",
                          query_string={"state": query["state"][0], "error": "access_denied"})
    assert response.status_code == 403
    assert "test users" in response.get_data(as_text=True)
    assert google["exchange"] == []


def test_a_token_without_read_access_is_not_kept(web_client, monkeypatch, client, auth_headers, config):
    monkeypatch.setattr(gmail_routes, "exchange_code", lambda *a: (FakeCreds(), {"openid"}))
    monkeypatch.setattr(gmail_routes, "gmail_address", lambda creds: ADDRESS)
    _, query = _start(client, auth_headers)
    response = _finish(client, query["state"][0])
    assert response.status_code == 403
    assert "tick the box" in response.get_data(as_text=True)
    assert connected_gmail(config, TEST_EMAIL) is None


def test_a_failed_exchange_says_try_again(web_client, monkeypatch, client, auth_headers, config):
    def fail(*args):
        raise RuntimeError("invalid_grant")

    monkeypatch.setattr(gmail_routes, "exchange_code", fail)
    _, query = _start(client, auth_headers)
    response = _finish(client, query["state"][0])
    assert response.status_code == 502
    assert "invalid_grant" not in response.get_data(as_text=True)
    assert connected_gmail(config, TEST_EMAIL) is None


def test_the_page_escapes_what_it_shows(web_client, monkeypatch, client, auth_headers):
    monkeypatch.setattr(gmail_routes, "exchange_code", lambda *a: (FakeCreds(), set(SCOPES)))
    monkeypatch.setattr(gmail_routes, "gmail_address", lambda creds: "<script>x</script>@gmail.com")
    page = _connect(client, auth_headers).get_data(as_text=True)
    assert "<script>x</script>" not in page


# --- which mailbox each user gets -------------------------------------------------------


def test_a_connected_user_is_served_their_own_gmail(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    source = get_email_source(config, TEST_EMAIL)
    assert isinstance(source, GmailApiSource)
    assert mailbox_of(config, TEST_EMAIL) == {"kind": "gmail", "address": ADDRESS, "own": True}


def test_everyone_else_still_gets_the_demo_mailbox(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    assert isinstance(get_email_source(config, "someone.else@example.com"), FixtureEmailSource)
    assert mailbox_of(config, "someone.else@example.com")["kind"] == "demo"


def test_the_inbox_says_whose_mailbox_it_is(web_client, google, monkeypatch, client, auth_headers):
    _connect(client, auth_headers)
    monkeypatch.setattr(GmailApiSource, "list_emails", lambda self: [])
    body = client.get("/api/inbox", headers=auth_headers).get_json()
    assert body["mailbox"] == {"kind": "gmail", "address": ADDRESS, "own": True}


def test_a_dead_user_token_points_to_settings_not_the_script(config):
    source = GmailApiSource(token_store=UserTokenStore(config, "nobody@example.com"),
                            reconnect="Connect Gmail again in Settings.")
    with pytest.raises(EmailSourceError, match="Settings"):
        source._credentials.get()


def test_a_token_that_no_longer_decrypts_counts_as_not_connected(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    rotated = copy.copy(config)
    rotated.jwt_secret = "a-different-secret"
    assert connected_gmail(rotated, TEST_EMAIL) is None
    assert isinstance(get_email_source(rotated, TEST_EMAIL), FixtureEmailSource)


def test_a_refreshed_token_is_saved_encrypted(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    store = UserTokenStore(config, TEST_EMAIL)
    store.save(json.dumps({"refresh_token": "rotated-token"}))
    assert b"rotated-token" not in open(config.accounts_db, "rb").read()
    assert json.loads(store.load())["refresh_token"] == "rotated-token"


# --- disconnecting ------------------------------------------------------------------------


def test_disconnect_revokes_and_forgets(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    response = client.post("/api/gmail/disconnect", headers=auth_headers)
    assert response.get_json() == {"connected": False, "revoked": True}
    assert google["revoke"] == [REFRESH]
    assert client.get("/api/gmail", headers=auth_headers).get_json()["connected"] is False
    assert isinstance(get_email_source(config, TEST_EMAIL), FixtureEmailSource)


def test_a_refresh_after_disconnect_does_not_bring_it_back(web_client, google, client, auth_headers, config):
    _connect(client, auth_headers)
    client.post("/api/gmail/disconnect", headers=auth_headers)
    UserTokenStore(config, TEST_EMAIL).save(FakeCreds().to_json())
    assert get_store(config).gmail_connection(TEST_EMAIL) is None


def test_disconnect_without_a_connection_is_harmless(client, auth_headers, google):
    response = client.post("/api/gmail/disconnect", headers=auth_headers)
    assert response.get_json() == {"connected": False, "revoked": False}
    assert google["revoke"] == []


def test_the_real_exchange_sends_the_verifier_and_reads_googles_reply(web_client, config, monkeypatch):
    """exchange_code with the real OAuth library; only the HTTP reply is fake.
    The other tests replace exchange_code, so this is what proves the verifier
    made at /connect is what reaches Google's token endpoint."""
    import requests
    from requests_oauthlib import OAuth2Session

    sent = {}

    def fake_request(self, method, url, data=None, **kwargs):
        form = dict(data) if isinstance(data, dict) else {k: v[0] for k, v in parse_qs(data or "").items()}
        sent.update(method=method, url=url, data=form)
        reply = requests.Response()
        reply.request = requests.Request(method, url, data=data).prepare()
        reply.status_code = 200
        reply.headers["Content-Type"] = "application/json"
        reply._content = json.dumps({
            "access_token": "a", "refresh_token": "r", "expires_in": 3599,
            "token_type": "Bearer", "scope": " ".join(SCOPES),
        }).encode()
        return reply

    monkeypatch.setattr(OAuth2Session, "request", fake_request)
    client_config = gmail_routes._client_config(config)
    creds, granted = gmail_routes.exchange_code(config, client_config, "4/code", "v" * 64)

    assert sent["url"] == "https://oauth2.googleapis.com/token"
    assert sent["data"]["code"] == "4/code"
    assert sent["data"]["code_verifier"] == "v" * 64
    assert sent["data"]["redirect_uri"] == config.gmail_redirect_uri
    assert granted == set(SCOPES)
    assert creds.refresh_token == "r"
    assert json.loads(creds.to_json())["refresh_token"] == "r"
