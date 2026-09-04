"""Shared test fixtures.

The test app is built with an explicit in-process config so the suite never
depends on a developer's .env or a real OpenAI key. CI must be able to run
these tests with no secrets configured.

On the stub client below: it exists so route wiring, validation, retry and
grounding behaviour can be exercised deterministically. It is not there to make
a feature look like it works. The tests that carry the real weight -- the
preprocessing tests, the grounding tests, the evidence-verification tests and
the intent target resolution tests -- call the production functions directly
with real strings and no stub anywhere near them. Where a stub is used, the
assertion is always about what the *backend* does with a given model response
(discard it, retry it, flag it, route it to Review), never about the model.
"""

import json
import os
import sys

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import create_app  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.orchestrator import cache as cache_module  # noqa: E402
from backend.orchestrator import client as client_module  # noqa: E402
from backend.orchestrator.budget import get_budget  # noqa: E402

TEST_EMAIL = "student@monash.edu"
TEST_PASSWORD = "correct-horse-battery-staple"

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backend", "adapters", "fixtures",
)

# Ids of the fixture messages, so tests can name one without re-parsing.
WORK_EMAIL_ID = "c8f21a04-work-001@northgate.com.au"
PROMO_EMAIL_ID = "7e02f9aa-promo-004@techdeals-mail.example"


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-used-in-production")
    # Point the delivery directory at an empty temp dir. The suite asserts on
    # the six committed fixtures, and a message the developer sent to the local
    # mail server must not change the mailbox the tests see.
    monkeypatch.setenv("EMAIL_INBOX_DIR", str(tmp_path / "mailbox"))
    monkeypatch.setenv(
        "AUTH_USERS",
        json.dumps({TEST_EMAIL: generate_password_hash(TEST_PASSWORD)}),
    )
    monkeypatch.setenv("EMAIL_FIXTURE_DIR", FIXTURE_DIR)
    return Config(require_llm=False)


@pytest.fixture(autouse=True)
def clean_state():
    """Reset the process-wide caches, budget and client between tests.

    These are module-level singletons by design (they back a stateless request
    handler). Without this, one test's cached summary silently satisfies the
    next test's assertion and the suite passes for the wrong reason.
    """
    cache_module.clear_all()
    client_module.reset_client()
    yield
    cache_module.clear_all()
    client_module.reset_client()


@pytest.fixture
def app(config):
    application = create_app(config)
    application.config.update(TESTING=True)
    get_budget(config).reset()
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


# --- Stub orchestrator client ----------------------------------------------


class StubLLM:
    """Returns queued responses instead of calling OpenAI.

    Mirrors OrchestratorClient.complete_json only. It does not reimplement the
    retry loop, the budget or the schema handling -- those are production code
    and are tested through the real client where they matter.
    """

    def __init__(self):
        self.responses = []
        self.calls = []
        self.raises = None

    def queue(self, *responses):
        """Queue one response per expected call, in order."""
        self.responses.extend(responses)
        return self

    def complete_json(self, system, user, schema_name, schema, purpose="", session_key=None):
        self.calls.append({
            "schema_name": schema_name,
            "purpose": purpose,
            "user": user,
            "system": system,
            "session_key": session_key,
        })
        if self.raises is not None:
            raise self.raises
        if not self.responses:
            raise AssertionError(
                f"StubLLM received an unexpected call ({schema_name}); "
                f"{len(self.calls)} call(s) made, no response queued."
            )
        return self.responses.pop(0)

    @property
    def call_count(self):
        return len(self.calls)


@pytest.fixture
def stub_llm():
    stub = StubLLM()
    client_module.set_client(stub)
    yield stub
    client_module.reset_client()
