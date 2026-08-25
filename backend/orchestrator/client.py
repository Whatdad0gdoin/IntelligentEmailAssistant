"""The single OpenAI wrapper (spec section 4, rule 4).

This is the only module in the project that imports the vendor SDK or knows the
model name. Routes, views and adapters call the feature modules; the feature
modules call this. Nothing else touches the API.

That boundary is worth the indirection: the settings that must hold for every
call -- temperature 0, a schema on the response, a timeout, retry once, the
session cap -- are applied here once instead of being re-remembered at each
call site. There is no path to the API that can skip them.

Logging (NFR-03): purpose, duration, retry count and token usage are logged.
Prompts and responses are not, because both contain email content.
"""

import json
import logging
import threading
import time

from backend.orchestrator.budget import get_budget

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Base for every orchestrator failure surfaced to a route."""


class LLMUnavailable(LLMError):
    """The API could not be reached, or failed twice."""


class LLMSchemaError(LLMError):
    """The response could not be used: refused, unparseable, or off-schema."""


class OrchestratorClient:
    """Wraps one OpenAI client with the project-wide call policy."""

    def __init__(self, config):
        self.config = config
        self._client = None
        self._lock = threading.Lock()

    def _sdk(self):
        """Build the SDK client lazily, so importing this module needs no key."""
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - environment issue
                raise LLMUnavailable(
                    "The openai package is not installed. "
                    "Run: pip install -r backend/requirements.txt"
                ) from exc

            if not self.config.openai_api_key:
                raise LLMUnavailable("OPENAI_API_KEY is not set. See backend/.env.example.")

            kwargs = {
                "api_key": self.config.openai_api_key,
                "timeout": self.config.openai_timeout_seconds,
                "max_retries": 0,  # retry policy is ours, below, so it stays observable
            }
            if self.config.openai_base_url:
                kwargs["base_url"] = self.config.openai_base_url
                # Azure OpenAI and most gateways select the REST contract with
                # an api-version query parameter. api.openai.com does not: it
                # has no request-level version selector, so against the public
                # endpoint the effective pin is the SDK version pinned in
                # backend/requirements.txt. Sending it here regardless would be
                # theatre, so it is only sent where it is actually read.
                if self.config.openai_api_version:
                    kwargs["default_query"] = {"api-version": self.config.openai_api_version}

            self._client = OpenAI(**kwargs)
            return self._client

    def complete_json(self, system, user, schema_name, schema, purpose="", session_key=None):
        """One schema-constrained completion. Returns the parsed object.

        Retries exactly once (section 4.1). The retry covers transient
        transport failures and a response that will not parse; it does not
        cover a response that parsed but failed a *content* rule, such as a
        summary of the wrong length. Those are the caller's to judge, because
        only the caller knows what valid means -- see summarise.py.
        """
        budget = get_budget(self.config)
        budget.spend(session_key)

        request = {
            "model": self.config.openai_model,
            "temperature": self.config.openai_temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }

        last_error = None
        for attempt in (1, 2):
            started = time.perf_counter()
            try:
                response = self._sdk().chat.completions.create(**request)
                elapsed = time.perf_counter() - started

                choice = response.choices[0]
                refusal = getattr(choice.message, "refusal", None)
                if refusal:
                    # A refusal is a valid API response, so it must not be
                    # retried blindly -- but it is not usable output either.
                    raise LLMSchemaError(f"The model declined this {purpose or 'request'}.")

                content = choice.message.content or ""
                parsed = json.loads(content)

                usage = getattr(response, "usage", None)
                log.info(
                    "llm %s: ok in %.2fs on attempt %d (prompt=%s, completion=%s tokens)",
                    purpose or schema_name,
                    elapsed,
                    attempt,
                    getattr(usage, "prompt_tokens", "?"),
                    getattr(usage, "completion_tokens", "?"),
                )
                return parsed

            except LLMSchemaError:
                raise
            except json.JSONDecodeError as exc:
                last_error = LLMSchemaError("The model returned output that was not valid JSON.")
                log.warning("llm %s: unparseable response on attempt %d", purpose, attempt)
                _ = exc
            except Exception as exc:
                last_error = LLMUnavailable(
                    "The AI service is unavailable. Please try again in a moment."
                )
                # Type name only: an exception string can carry request content.
                log.warning(
                    "llm %s: %s on attempt %d after %.2fs",
                    purpose,
                    type(exc).__name__,
                    attempt,
                    time.perf_counter() - started,
                )

            if attempt == 1:
                # The retry is a second chance at the same call, and it is not
                # free, so it is charged to the session budget like any other.
                budget.spend(session_key)

        raise last_error or LLMUnavailable("The AI service is unavailable.")


# --- Client access ---------------------------------------------------------

_clients = {}
_registry_lock = threading.Lock()
_override = None


def get_client(config):
    """Return the client for this config, building it once."""
    if _override is not None:
        return _override
    key = (config.openai_model, config.openai_base_url, id(config))
    with _registry_lock:
        if key not in _clients:
            _clients[key] = OrchestratorClient(config)
        return _clients[key]


def set_client(client):
    """Test seam: substitute the client for every caller.

    Used by the suite so tests can exercise validation, grounding and routing
    without a network call or an API key. It is not a way to fake a feature
    working -- the tests that use it assert on what the *backend* does with a
    given response, and the tests that matter most (preprocessing, grounding,
    evidence verification, the intent harness) do not go near a model at all.
    """
    global _override
    _override = client


def reset_client():
    global _override
    _override = None
