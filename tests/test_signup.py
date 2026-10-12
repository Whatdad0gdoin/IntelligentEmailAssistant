"""Sign-up (routes/auth.py) and the accounts it creates (backend/accounts.py).

A new account signs straight in, can sign in again later, and sees the demo
mailbox until its owner connects Gmail. The checks that matter most are the
ones that keep sign-up from weakening login: passwords stored only as hashes,
no second account for an address, and no answers about existing accounts to
anyone without the invite code when one is set.
"""

import pytest

from backend.accounts import get_store
from tests.conftest import TEST_EMAIL

NEW_EMAIL = "new.user@example.com"
NEW_PASSWORD = "a-long-enough-password"


def _signup(client, email=NEW_EMAIL, password=NEW_PASSWORD, **extra):
    return client.post("/api/auth/signup", json={"email": email, "password": password, **extra})


def test_signup_options_are_public_and_say_whether_a_code_is_needed(client):
    response = client.get("/api/auth/signup")
    assert response.status_code == 200
    assert response.get_json() == {"enabled": True, "invite_code_required": False}


def test_signup_creates_an_account_and_signs_in(client):
    response = _signup(client)
    assert response.status_code == 201
    token = response.get_json()["token"]

    # The token works on a protected route straight away.
    me = client.get("/api/gmail", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_a_new_account_can_sign_in_again(client):
    _signup(client)
    response = client.post("/api/auth/login", json={"email": NEW_EMAIL, "password": NEW_PASSWORD})
    assert response.status_code == 200
    assert "token" in response.get_json()


def test_the_address_is_stored_lowercase(client):
    _signup(client, email="  Mixed.Case@Example.COM ")
    response = client.post(
        "/api/auth/login", json={"email": "mixed.case@example.com", "password": NEW_PASSWORD}
    )
    assert response.status_code == 200


def test_a_wrong_password_for_a_new_account_is_the_usual_401(client):
    _signup(client)
    response = client.post("/api/auth/login", json={"email": NEW_EMAIL, "password": "not-it-at-all"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "Invalid email or password"}


def test_the_password_is_stored_only_as_a_hash(client, config):
    _signup(client)
    raw = open(config.accounts_db, "rb").read()
    assert NEW_PASSWORD.encode() not in raw
    assert get_store(config).password_hash(NEW_EMAIL).startswith(("scrypt:", "pbkdf2:"))


def test_the_same_address_cannot_sign_up_twice(client):
    assert _signup(client).status_code == 201
    response = _signup(client, password="a-different-password")
    assert response.status_code == 409
    assert "already exists" in response.get_json()["error"]


def test_an_address_in_auth_users_cannot_be_taken_by_sign_up(client):
    response = _signup(client, email=TEST_EMAIL)
    assert response.status_code == 409


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "two@@example.com", "spa ce@example.com"])
def test_an_unusable_address_is_refused(client, email):
    response = _signup(client, email=email)
    assert response.status_code == 400
    assert "email address" in response.get_json()["error"]


@pytest.mark.parametrize("password", ["", "short", "x" * 129])
def test_a_password_outside_the_length_rule_is_refused(client, password):
    response = _signup(client, password=password)
    assert response.status_code == 400
    assert "8 to 128" in response.get_json()["error"]


def test_nothing_is_written_when_sign_up_is_refused(client, config):
    _signup(client, password="short")
    assert get_store(config).password_hash(NEW_EMAIL) is None


# --- invite code -------------------------------------------------------------------


@pytest.fixture
def invite_only(app, config):
    config.signup_code = "let-me-in"
    return app


def test_the_form_is_told_a_code_is_needed(invite_only, client):
    assert client.get("/api/auth/signup").get_json()["invite_code_required"] is True


def test_without_the_code_sign_up_is_refused(invite_only, client):
    response = _signup(client)
    assert response.status_code == 403
    response = _signup(client, invite_code="guess")
    assert response.status_code == 403


def test_with_the_code_sign_up_works(invite_only, client):
    assert _signup(client, invite_code="let-me-in").status_code == 201


def test_without_the_code_existing_accounts_are_not_revealed(invite_only, client):
    """The code is checked first, so a stranger learns nothing about which
    addresses have accounts: the answer is the same 403 either way."""
    taken = _signup(client, email=TEST_EMAIL, invite_code="guess")
    free = _signup(client, email="free@example.com", invite_code="guess")
    assert taken.status_code == free.status_code == 403
    assert taken.get_json() == free.get_json()


def test_sign_up_can_be_turned_off(app, config, client):
    config.signup_enabled = False
    assert client.get("/api/auth/signup").get_json()["enabled"] is False
    assert _signup(client).status_code == 403


# --- what a new account sees ---------------------------------------------------------


def test_a_new_account_sees_the_demo_mailbox_and_is_told_so(client, stub_llm):
    token = _signup(client).get_json()["token"]
    stub_llm.answer_classification({})
    response = client.get("/api/inbox", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["mailbox"] == {"kind": "demo", "address": None, "own": False}
