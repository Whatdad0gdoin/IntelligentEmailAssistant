"""Orchestrator client policy tests (spec section 4.1).

Every model call must be temperature 0, schema-constrained, timeout-bounded,
retried exactly once, and charged to the session cap. These are the settings
the whole project depends on, so they are tested on the real
OrchestratorClient with a fake SDK underneath it -- not on the stub, which
would prove nothing about the policy.
"""

import json

import pytest

from backend.orchestrator.budget import BudgetExceeded, get_budget
from backend.orchestrator.client import (
    LLMSchemaError,
    LLMUnavailable,
    OrchestratorClient,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["value"],
    "properties": {"value": {"type": "string"}},
}


class FakeMessage:
    def __init__(self, content, refusal=None):
        self.content = content
        self.refusal = refusal


class FakeChoice:
    def __init__(self, content, refusal=None):
        self.message = FakeMessage(content, refusal)


class FakeResponse:
    def __init__(self, content, refusal=None):
        self.choices = [FakeChoice(content, refusal)]
        self.usage = None


class FakeSDK:
    """Stands in for openai.OpenAI. Records calls, returns scripted results."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        parent = self

        class Completions:
            def create(self, **kwargs):
                parent.requests.append(kwargs)
                outcome = parent.outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        class Chat:
            completions = Completions()

        self.chat = Chat()

    @property
    def call_count(self):
        return len(self.requests)


def _client(config, sdk):
    client = OrchestratorClient(config)
    client._sdk = lambda: sdk
    return client


def _call(client, session_key=None):
    return client.complete_json(
        system="sys", user="usr", schema_name="thing", schema=SCHEMA,
        purpose="test", session_key=session_key,
    )


def _ok(value="hello"):
    return FakeResponse(json.dumps({"value": value}))


# --- Universal settings ----------------------------------------------------


def test_temperature_is_zero(config):
    sdk = FakeSDK(_ok())
    _call(_client(config, sdk))
    assert sdk.requests[0]["temperature"] == 0


def test_the_model_comes_from_config(config):
    config.openai_model = "some-configured-model"
    sdk = FakeSDK(_ok())
    _call(_client(config, sdk))
    assert sdk.requests[0]["model"] == "some-configured-model"


def test_the_response_is_schema_constrained(config):
    """No free-text parsing anywhere: the schema is on the request."""
    sdk = FakeSDK(_ok())
    _call(_client(config, sdk))
    response_format = sdk.requests[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == SCHEMA


def test_the_parsed_object_is_returned(config):
    assert _call(_client(config, FakeSDK(_ok("hello")))) == {"value": "hello"}


# --- Retry once (section 4.1) ----------------------------------------------


def test_a_transient_failure_is_retried_once_and_can_succeed(config):
    sdk = FakeSDK(TimeoutError("connection reset"), _ok("recovered"))
    assert _call(_client(config, sdk)) == {"value": "recovered"}
    assert sdk.call_count == 2


def test_two_failures_raise_rather_than_returning_something_empty(config):
    sdk = FakeSDK(TimeoutError("down"), TimeoutError("still down"))
    with pytest.raises(LLMUnavailable):
        _call(_client(config, sdk))
    assert sdk.call_count == 2


def test_it_retries_once_and_not_forever(config):
    sdk = FakeSDK(*[TimeoutError("down")] * 5)
    with pytest.raises(LLMUnavailable):
        _call(_client(config, sdk))
    assert sdk.call_count == 2, "retry-once means two attempts total"


def test_unparseable_json_is_retried_then_raises_a_schema_error(config):
    sdk = FakeSDK(FakeResponse("not json at all"), FakeResponse("still not json"))
    with pytest.raises(LLMSchemaError):
        _call(_client(config, sdk))
    assert sdk.call_count == 2


def test_a_refusal_is_not_retried(config):
    """A refusal is a considered answer, so asking again is a waste of budget."""
    sdk = FakeSDK(FakeResponse(None, refusal="I cannot help with that."))
    with pytest.raises(LLMSchemaError):
        _call(_client(config, sdk))
    assert sdk.call_count == 1


def test_the_error_message_carries_no_request_content(config):
    """An exception string can be logged or shown; it must not leak the email."""
    sdk = FakeSDK(
        TimeoutError("failed while sending: the quarterly report is attached"),
        TimeoutError("failed while sending: the quarterly report is attached"),
    )
    with pytest.raises(LLMUnavailable) as raised:
        _call(_client(config, sdk))
    assert "quarterly report" not in str(raised.value)


# --- Per-session request cap (section 4.1) ---------------------------------


def test_calls_are_charged_to_the_session(config):
    config.max_requests_per_session = 10
    budget = get_budget(config)
    budget.reset()
    client = _client(config, FakeSDK(_ok(), _ok()))
    _call(client, session_key="user:1")
    _call(client, session_key="user:1")
    assert budget.used("user:1") == 2


def test_exceeding_the_cap_raises_before_the_call_goes_out(config):
    config.max_requests_per_session = 2
    budget = get_budget(config)
    budget.reset()
    sdk = FakeSDK(_ok(), _ok(), _ok())
    client = _client(config, sdk)
    _call(client, session_key="user:1")
    _call(client, session_key="user:1")
    with pytest.raises(BudgetExceeded):
        _call(client, session_key="user:1")
    assert sdk.call_count == 2, "the over-budget call must not reach the API"


def test_a_retry_is_charged_too(config):
    """A retry costs real money, so it counts against the cap."""
    config.max_requests_per_session = 10
    budget = get_budget(config)
    budget.reset()
    client = _client(config, FakeSDK(TimeoutError("x"), _ok()))
    _call(client, session_key="user:1")
    assert budget.used("user:1") == 2


def test_sessions_have_separate_allowances(config):
    config.max_requests_per_session = 1
    budget = get_budget(config)
    budget.reset()
    client = _client(config, FakeSDK(_ok(), _ok()))
    _call(client, session_key="user:login-1")
    _call(client, session_key="user:login-2")
    assert budget.used("user:login-1") == 1
    assert budget.used("user:login-2") == 1


def test_the_cap_is_read_from_config(config):
    config.max_requests_per_session = 1
    budget = get_budget(config)
    budget.reset()
    client = _client(config, FakeSDK(_ok(), _ok()))
    _call(client, session_key="user:1")
    with pytest.raises(BudgetExceeded):
        _call(client, session_key="user:1")


def test_the_budget_error_tells_the_user_what_to_do(config):
    config.max_requests_per_session = 1
    budget = get_budget(config)
    budget.reset()
    client = _client(config, FakeSDK(_ok(), _ok()))
    _call(client, session_key="user:1")
    with pytest.raises(BudgetExceeded) as raised:
        _call(client, session_key="user:1")
    assert "Sign in again" in str(raised.value)
