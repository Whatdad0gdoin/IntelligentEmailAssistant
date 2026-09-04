"""Environment-driven configuration.

Nothing in this project is hardcoded: model name, API key, temperature, budget
cap and API version are all read from the environment (spec section 1).

Values are read once at import time. Missing *required* values raise at startup
rather than at first request, so a misconfigured deployment fails loudly instead
of failing halfway through a user's session.
"""

import json
import os


class ConfigError(RuntimeError):
    """Raised at startup when a required environment variable is missing."""


def _require(name):
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"Required environment variable {name} is not set. "
            f"Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


def _optional(name, default):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _float(name, default):
    return float(_optional(name, default))


def _int(name, default):
    return int(_optional(name, default))


class Config:
    """Application configuration.

    Instantiated per app so tests can build one with a patched environment.
    """

    def __init__(self, require_llm=True, require_auth=True):
        # --- Auth (NFR-04) -------------------------------------------------
        # require_auth is False for processes that are not the API and have no
        # business holding a signing secret -- the mail server reads only the
        # SMTP and mailbox settings from this object.
        self.jwt_secret = _require("JWT_SECRET") if require_auth else _optional("JWT_SECRET", "")
        self.jwt_algorithm = _optional("JWT_ALGORITHM", "HS256")
        self.jwt_expires_in = _int("JWT_EXPIRES_IN", 3600)

        # AUTH_USERS is a JSON object mapping email -> password hash.
        # Generate a hash with:  python -m backend.scripts.hash_password
        raw_users = _optional("AUTH_USERS", "{}")
        try:
            self.auth_users = json.loads(raw_users)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"AUTH_USERS is not valid JSON: {exc}") from exc
        if not isinstance(self.auth_users, dict):
            raise ConfigError("AUTH_USERS must be a JSON object of email -> password hash")

        # --- LLM orchestrator (section 4.1) --------------------------------
        # require_llm is False for auth-only tests and for CI, which must not
        # need a real API key to run.
        self.openai_api_key = _require("OPENAI_API_KEY") if require_llm else _optional("OPENAI_API_KEY", "")
        self.openai_model = _optional("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_api_version = _optional("OPENAI_API_VERSION", "2024-10-21")
        self.openai_temperature = _float("OPENAI_TEMPERATURE", "0")
        self.openai_timeout_seconds = _float("OPENAI_TIMEOUT_SECONDS", "20")
        # Optional. Set for Azure OpenAI or a local gateway; empty means the
        # SDK default (api.openai.com).
        self.openai_base_url = _optional("OPENAI_BASE_URL", "")

        # Budget governance. The FIT3163 settings wireframe specifies a $5/week
        # cap; the per-session request cap is the mechanism that enforces it.
        self.max_requests_per_session = _int("MAX_REQUESTS_PER_SESSION", 100)
        self.token_budget_chars = _int("TOKEN_BUDGET_CHARS", 12000)

        # --- Grounding thresholds (section 4.3) ----------------------------
        self.classify_confidence_threshold = _float("CLASSIFY_CONFIDENCE_THRESHOLD", "0.7")

        # --- Latency (NFR-01) ----------------------------------------------
        # The Week 6 deck states < 5 seconds; that is the number we report against.
        self.latency_target_seconds = _float("LATENCY_TARGET_SECONDS", "5")
        self.metrics_window = _int("METRICS_WINDOW", 100)

        # --- Email source adapter (section 1) -------------------------------
        # "fixture" reads RFC-822 .eml files from disk. That directory stands in
        # for the mail server, exactly as an IMAP host would; it is the *source*
        # of email, not the app persisting anything (NFR-03). A real source
        # slots in behind the same interface without touching routes.
        self.email_source = _optional("EMAIL_SOURCE", "fixture")
        self.email_fixture_dir = _optional(
            "EMAIL_FIXTURE_DIR",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "adapters", "fixtures"),
        )

        # Where the local mail server delivers received messages. Read together
        # with the fixture directory, so a message sent to the app appears
        # alongside the demo mailbox with no configuration.
        #
        # Separate from the fixtures on purpose: those are curated, committed
        # and asserted on by the test suite. Received mail landing in that
        # directory would change the mailbox out from under the tests.
        self.email_inbox_dir = _optional(
            "EMAIL_INBOX_DIR",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "mailbox"),
        )

        # SMTP receiver (backend/mailserver.py). 127.0.0.1 accepts only from
        # this machine; SMTP_HOST=0.0.0.0 accepts from other devices on the
        # same network, which is how you send from a phone.
        self.smtp_host = _optional("SMTP_HOST", "127.0.0.1")
        self.smtp_port = _int("SMTP_PORT", 2525)
        self.smtp_max_bytes = _int("SMTP_MAX_BYTES", 5000000)
        # Length of the header-derived preview shown in the inbox list.
        self.snippet_chars = _int("SNIPPET_CHARS", 140)

        # --- Voice (FR-05) ---------------------------------------------------
        # Below this, the UI shows the transcript back and asks the user to pick
        # an action rather than dispatching (section 6.3).
        self.intent_confidence_threshold = _float("INTENT_CONFIDENCE_THRESHOLD", "0.6")

        # --- CORS -----------------------------------------------------------
        self.cors_origins = [
            o.strip() for o in _optional("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ]
