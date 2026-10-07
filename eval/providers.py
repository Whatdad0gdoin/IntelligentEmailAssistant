"""Model adapters for the provider comparison (eval/compare_models.py).

Every feature module calls exactly one method on the model client:

    complete_json(system, user, schema_name, schema, purpose, session_key)

Each class below implements that method for one provider, so classify_emails,
classify_intent and summarise_email run UNCHANGED against it -- same prompts,
same schemas, same evidence verification, same confidence threshold, same
scoring code. They are installed with backend.orchestrator.client.set_client(),
the seam the test suite already uses. Nothing under backend/ is modified, and
the shipped configuration (backend/.env -> gpt-4o-mini through client.py) is
untouched.

This is measuring equipment, not a second production client. It mirrors
client.py's call policy where the providers allow it -- one retry, a wait
before the retry on rate limits and server errors, no retry on a refusal --
so that differences in the results are differences between models rather than
between wrappers. Where a provider does not allow the same settings, the
adapter says so in `settings` and the comparison report prints it:

- Claude Sonnet 5.5 and Opus 5.5 reject a non-default temperature, and Opus 5.5
  always thinks. They run at effort "low".
- Google recommends temperature 1.0 for every Gemini 3 model (lower values can
  loop or degrade), and Gemini 3 always thinks to some degree. They run at
  thinking_level "low" and the default temperature.
- gpt-4o-mini and Claude Haiku 4.5 run at temperature 0 with no thinking, as
  the shipped configuration does. gpt-5-mini is a reasoning model: default
  temperature only, reasoning_effort "low".

So "temperature 0" is not held constant across the comparison, and cannot be.

Every call is recorded -- latency, attempts, tokens, outcome -- so cost,
latency and reliability come from what actually happened, not from a price
list multiplied by a guess.

Needs, beyond backend/requirements.txt:

    pip install anthropic google-genai

with ANTHROPIC_API_KEY and GEMINI_API_KEY in the environment (OPENAI_API_KEY
comes from backend/.env as usual).
"""

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from backend.orchestrator.client import (
    DEFAULT_BASE_URL,
    LLMSchemaError,
    LLMUnavailable,
    MAX_RETRY_WAIT_SECONDS,
    DEFAULT_RETRY_WAIT_SECONDS,
)

# USD per 1M tokens, (input, output). Output includes thinking/reasoning tokens
# for every provider here, because all three bill them as output.
#   OpenAI:    developers.openai.com/api/docs/pricing, read 2026-10-06
#   Anthropic: first-party price table, Anthropic API docs (cached 2026-09-25)
#   Google:    ai.google.dev/gemini-api/docs/pricing, read 2026-10-06
# Gemini 3.8 Flash is on a promotional price until 2026-12-31 and doubles to
# $1.50 / $7.50 from 2027-01-01; PRICE_NOTES carries that into the report.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5-mini": (0.25, 2.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}
PRICE_NOTES = {
    "gemini-3.8-flash": "promotional until 2026-12-31; $1.50 / $7.50 per 1M from 2027-01-01",
    "gemini-3.1-pro-preview": "preview model: can change or be withdrawn at short notice",
}


@dataclass
class CallRecord:
    """One complete_json call, successful or not."""

    provider: str
    model: str
    purpose: str
    ok: bool = False
    error: str = ""            # exception type name only -- never message text
    attempts: int = 0
    seconds: float = 0.0       # wall clock for the whole call, retries included
    attempt_seconds: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0     # billed output, thinking included
    thinking_tokens: int = 0   # the part of output_tokens that was thinking
    cached_tokens: int = 0
    refused: bool = False
    unparseable: int = 0       # attempts whose body was not valid JSON


def _retryable(exc):
    """Seconds to wait before the one retry, or None if a retry cannot help.

    The same split client.py makes: rate limits, timeouts, connection failures
    and server errors are worth one more try; a malformed request is not.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    name = type(exc).__name__
    transient_name = any(word in name for word in
                         ("RateLimit", "Timeout", "Connection", "InternalServer",
                          "Overloaded", "ServiceUnavailable", "ServerError"))
    transient_status = isinstance(status, int) and (status in (408, 409, 429) or status >= 500)
    if not (transient_name or transient_status):
        return None
    for source in (getattr(exc, "response", None), exc):
        headers = getattr(source, "headers", None) or {}
        value = headers.get("retry-after") if hasattr(headers, "get") else None
        if value:
            try:
                return min(max(float(value), 0.0), MAX_RETRY_WAIT_SECONDS)
            except (TypeError, ValueError):
                pass
    return DEFAULT_RETRY_WAIT_SECONDS


class Adapter:
    """complete_json with the project's retry policy and per-call records."""

    provider = "?"

    def __init__(self, model, **settings):
        self.model = model
        self.settings = settings
        self.records = []
        self.last_payload = None   # the parsed response of the latest call
        self._lock = threading.Lock()

    # Subclasses return (text, usage dict, refused bool).
    def _call(self, system, user, schema_name, schema):  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, system, user, schema_name, schema, purpose="", session_key=None):
        record = CallRecord(provider=self.provider, model=self.model,
                            purpose=purpose or schema_name)
        started = time.perf_counter()
        last_error = None
        try:
            for attempt in (1, 2):
                record.attempts = attempt
                attempt_started = time.perf_counter()
                try:
                    text, usage, refused = self._call(system, user, schema_name, schema)
                    record.attempt_seconds.append(round(time.perf_counter() - attempt_started, 3))
                    # Usage is charged per attempt, so a retried call costs
                    # what both attempts cost.
                    record.input_tokens += usage.get("input", 0)
                    record.output_tokens += usage.get("output", 0)
                    record.thinking_tokens += usage.get("thinking", 0)
                    record.cached_tokens += usage.get("cached", 0)
                    if refused:
                        record.refused = True
                        raise LLMSchemaError(f"The model declined this {purpose or 'request'}.")
                    try:
                        parsed = json.loads(text or "")
                    except json.JSONDecodeError:
                        record.unparseable += 1
                        last_error = LLMSchemaError("The model returned output that was not valid JSON.")
                        continue
                    record.ok = True
                    self.last_payload = parsed
                    return parsed
                except LLMSchemaError:
                    raise
                except Exception as exc:  # transport and API errors
                    record.attempt_seconds.append(round(time.perf_counter() - attempt_started, 3))
                    record.error = type(exc).__name__
                    last_error = LLMUnavailable("The AI service is unavailable.")
                    # client.py retries once on ANY failure and only waits
                    # first when waiting can help; mirrored exactly.
                    wait = _retryable(exc)
                    if wait and attempt == 1:
                        time.sleep(wait)
            raise last_error or LLMUnavailable("The AI service is unavailable.")
        except LLMSchemaError as exc:
            record.error = record.error or type(exc).__name__
            raise
        finally:
            record.seconds = round(time.perf_counter() - started, 3)
            with self._lock:
                self.records.append(record)

    def describe(self):
        return {"provider": self.provider, "model": self.model, **self.settings}

    def drain(self):
        """Return and clear the records collected so far."""
        with self._lock:
            out, self.records = self.records, []
        return [asdict(r) for r in out]


# --- OpenAI -----------------------------------------------------------------

class OpenAIAdapter(Adapter):
    """The same request client.py sends: chat.completions, json_schema strict.

    For gpt-4o-mini the payload is byte-for-byte the shipped one (model,
    temperature, messages, response_format), so its run doubles as a check
    that this harness reproduces the production path.
    """

    provider = "openai"

    def __init__(self, model, temperature=0.0, reasoning_effort=None):
        super().__init__(model, temperature=temperature, reasoning_effort=reasoning_effort)
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMUnavailable("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=key,
                              base_url=os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL,
                              timeout=60, max_retries=0)

    def _call(self, system, user, schema_name, schema):
        request = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema_name, "strict": True,
                                                "schema": schema}},
        }
        if self.settings.get("reasoning_effort"):
            # Reasoning models accept only the default temperature.
            request["reasoning_effort"] = self.settings["reasoning_effort"]
        elif self.settings.get("temperature") is not None:
            request["temperature"] = self.settings["temperature"]
        response = self._client.chat.completions.create(**request)
        message = response.choices[0].message
        usage = response.usage
        details = getattr(usage, "completion_tokens_details", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        return (message.content or "", {
            "input": getattr(usage, "prompt_tokens", 0) or 0,
            "output": getattr(usage, "completion_tokens", 0) or 0,
            "thinking": getattr(details, "reasoning_tokens", 0) or 0,
            "cached": getattr(prompt_details, "cached_tokens", 0) or 0,
        }, bool(getattr(message, "refusal", None)))


# --- Anthropic --------------------------------------------------------------

# Structured outputs on the Claude API accept a JSON Schema subset; these
# keywords are rejected rather than ignored. The project already enforces
# counts and ranges in Python (schemas.py says so), so removing them from what
# is sent changes nothing that is checked.
_UNSUPPORTED_BY_CLAUDE = {"minItems", "maxItems", "minimum", "maximum",
                          "minLength", "maxLength", "multipleOf"}


def _strip_keywords(node, banned):
    if isinstance(node, dict):
        return {k: _strip_keywords(v, banned) for k, v in node.items() if k not in banned}
    if isinstance(node, list):
        return [_strip_keywords(v, banned) for v in node]
    return node


class AnthropicAdapter(Adapter):
    """Messages API with output_config.format (JSON-schema structured output).

    No refusal fallback is configured: a fallback answers with a different
    model, which would contaminate a per-model measurement. Refusals are
    counted instead. A production integration should enable one.
    """

    provider = "anthropic"

    def __init__(self, model, effort=None, temperature=None, max_tokens=16000):
        super().__init__(model, effort=effort, temperature=temperature, max_tokens=max_tokens)
        import anthropic
        self._client = anthropic.Anthropic(timeout=120, max_retries=0)

    def _call(self, system, user, schema_name, schema):
        output_config = {"format": {"type": "json_schema",
                                    "schema": _strip_keywords(schema, _UNSUPPORTED_BY_CLAUDE)}}
        if self.settings.get("effort"):
            output_config["effort"] = self.settings["effort"]
        request = {
            "model": self.model,
            "max_tokens": self.settings["max_tokens"],
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        if self.settings.get("temperature") is not None:
            request["temperature"] = self.settings["temperature"]
        response = self._client.messages.create(**request)
        refused = response.stop_reason == "refusal"
        text = next((b.text for b in response.content if b.type == "text"), "")
        if response.stop_reason == "max_tokens":
            text = ""  # truncated JSON is not an answer; counted as unparseable
        usage = response.usage
        return (text, {
            "input": (usage.input_tokens or 0)
                     + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                     + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
            "output": usage.output_tokens or 0,
            "thinking": 0,  # billed inside output_tokens; not reported separately
            "cached": getattr(usage, "cache_read_input_tokens", 0) or 0,
        }, refused)


# --- Google Gemini ----------------------------------------------------------

class GeminiAdapter(Adapter):
    """generate_content with response_json_schema (JSON-schema structured output)."""

    provider = "google"

    def __init__(self, model, thinking_level=None, thinking_budget=None, temperature=None):
        super().__init__(model, thinking_level=thinking_level,
                         thinking_budget=thinking_budget, temperature=temperature)
        from google import genai
        from google.genai import types
        self._types = types
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=key,
                                    http_options=types.HttpOptions(timeout=120_000))

    def _call(self, system, user, schema_name, schema):
        types = self._types
        thinking = None
        if self.settings.get("thinking_level"):
            thinking = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self.settings["thinking_level"].upper()))
        elif self.settings.get("thinking_budget") is not None:
            thinking = types.ThinkingConfig(thinking_budget=self.settings["thinking_budget"])
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=self.settings.get("temperature"),
            thinking_config=thinking,
        )
        response = self._client.models.generate_content(
            model=self.model, contents=user, config=config)
        usage = response.usage_metadata
        candidates = getattr(usage, "candidates_token_count", 0) or 0
        thoughts = getattr(usage, "thoughts_token_count", 0) or 0
        refused = False
        finish = None
        if response.candidates:
            finish = str(getattr(response.candidates[0], "finish_reason", "") or "")
        feedback = getattr(response, "prompt_feedback", None)
        if (feedback is not None and getattr(feedback, "block_reason", None)) or \
                any(word in (finish or "") for word in ("SAFETY", "PROHIBITED", "BLOCKLIST")):
            refused = True
        try:
            text = response.text or ""
        except Exception:
            text = ""
        return (text, {
            "input": getattr(usage, "prompt_token_count", 0) or 0,
            "output": candidates + thoughts,
            "thinking": thoughts,
            "cached": getattr(usage, "cached_content_token_count", 0) or 0,
        }, refused)


# --- The line-up --------------------------------------------------------------

def build(model):
    """The adapter, with the settings, each model is compared under."""
    if model == "gpt-4o-mini":
        return OpenAIAdapter(model, temperature=0.0)
    if model == "gpt-5-mini":
        # Reasoning models accept only the default temperature, so none is sent.
        return OpenAIAdapter(model, temperature=None, reasoning_effort="low")
    if model == "claude-haiku-4-5":
        return AnthropicAdapter(model, temperature=0.0)
    if model in ("claude-sonnet-5-5", "claude-opus-5-5"):
        return AnthropicAdapter(model, effort="low")
    # gemini-2.5-flash-lite was the price match for gpt-4o-mini, but on
    # 2026-10-06 it answered 404 "no longer available to new users" although
    # models.list() still returned it. A listed model is not an available one.
    if model.startswith("gemini-3"):
        return GeminiAdapter(model, thinking_level="low")
    raise ValueError(f"No adapter settings defined for {model}")


def cost_usd(model, input_tokens, output_tokens):
    price_in, price_out = PRICES[model]
    return input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out
