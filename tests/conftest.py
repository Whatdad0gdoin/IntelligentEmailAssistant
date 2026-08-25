"""Shared test fixtures.

The test app is built with an explicit in-process config so the suite never
depends on a developer's .env or a real OpenAI key. CI must be able to run
these tests with no secrets configured.
"""

import os
import sys

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import create_app  # noqa: E402
from backend.config import Config  # noqa: E402

TEST_EMAIL = "student@monash.edu"
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-used-in-production")
    monkeypatch.setenv(
        "AUTH_USERS",
        '{"%s": "%s"}' % (TEST_EMAIL, generate_password_hash(TEST_PASSWORD)),
    )
    return Config(require_llm=False)


@pytest.fixture
def app(config):
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def token(client):
    response = client.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}
