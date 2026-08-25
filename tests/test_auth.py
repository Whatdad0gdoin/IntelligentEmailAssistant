"""NFR-04: authentication is required before any email data is accessible.

The central test here enumerates the app's own URL map rather than listing
routes by hand. A route added later is picked up automatically: if a developer
forgets to allowlist it as public, it must still return 401.
"""

import datetime as _dt

import jwt
import pytest

from backend.middleware.jwt import PUBLIC_ENDPOINTS
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def _protected_rules(app):
    """Every routable rule that is not explicitly public."""
    rules = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS or rule.endpoint == "static":
            continue
        path = str(rule)
        for arg in rule.arguments:
            for pattern in (f"<{arg}>", f"<string:{arg}>", f"<int:{arg}>", f"<path:{arg}>"):
                path = path.replace(pattern, "placeholder")
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            rules.append((method, path))
    return rules


def test_url_map_is_not_empty(app):
    """Guards the enumeration test below from silently passing on zero routes."""
    assert len(list(app.url_map.iter_rules())) > 1


def test_every_protected_route_returns_401_without_token(app, client):
    protected = _protected_rules(app)
    if not protected:
        # Deliberately a skip, not a pass. Asserting over an empty set is a
        # green tick that proves nothing. Protected routes arrive with
        # /api/inbox in step 4; this test activates itself the moment they do.
        pytest.skip("no protected routes registered yet -- nothing to enumerate")
    failures = []
    for method, path in protected:
        response = client.open(path, method=method)
        if response.status_code != 401:
            failures.append(f"{method} {path} -> {response.status_code} (expected 401)")
    assert not failures, "Unauthenticated access was permitted:\n" + "\n".join(failures)


def test_unmatched_api_path_requires_auth_too(client):
    """An unauthenticated caller must not be able to probe which routes exist."""
    assert client.get("/api/does-not-exist").status_code == 401


def test_public_endpoints_are_deliberately_short(app):
    """A tripwire: widening the public allowlist should be a conscious act."""
    assert PUBLIC_ENDPOINTS == frozenset({"auth.login", "health.healthz"})


# --- login behaviour -------------------------------------------------------


def test_login_returns_token_and_expiry(client):
    response = client.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["expires_in"] == 3600
    assert isinstance(data["token"], str) and data["token"]


def test_login_is_case_insensitive_on_email(client):
    response = client.post(
        "/api/auth/login", json={"email": TEST_EMAIL.upper(), "password": TEST_PASSWORD}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"email": TEST_EMAIL, "password": "wrong-password"},
        {"email": "nobody@monash.edu", "password": TEST_PASSWORD},
        {"email": "", "password": ""},
        {},
    ],
)
def test_bad_credentials_return_401(client, payload):
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 401


def test_no_user_enumeration_in_error_message(client):
    """Unknown email and wrong password must be indistinguishable."""
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@monash.edu", "password": "x"}
    )
    wrong_pw = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": "x"})
    assert unknown.status_code == wrong_pw.status_code == 401
    assert unknown.get_json() == wrong_pw.get_json()


def test_login_response_never_contains_the_password(client):
    response = client.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert TEST_PASSWORD not in response.get_data(as_text=True)


# --- token validation ------------------------------------------------------


def test_valid_token_passes_the_guard(client, auth_headers):
    """404 here only means something because the same path 401s without a token.

    Paired with test_unmatched_api_path_requires_auth_too, this shows the guard
    ran, accepted the token, and handed off to routing.
    """
    assert client.get("/api/does-not-exist").status_code == 401
    assert client.get("/api/does-not-exist", headers=auth_headers).status_code == 404


def test_malformed_authorization_header_is_rejected(client):
    for header in ["", "Bearer", "Bearer ", "Token abc", "abc"]:
        response = client.get("/api/does-not-exist", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_token_signed_with_wrong_secret_is_rejected(client):
    forged = jwt.encode({"sub": TEST_EMAIL}, "not-the-real-secret", algorithm="HS256")
    response = client.get("/api/does-not-exist", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client, config):
    past = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=10)
    expired = jwt.encode(
        {"sub": TEST_EMAIL, "iat": past - _dt.timedelta(seconds=60), "exp": past},
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    response = client.get("/api/does-not-exist", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_health_is_public(client):
    assert client.get("/api/healthz").status_code == 200
