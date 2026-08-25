"""Log redaction (NFR-03).

Email bodies must never reach disk or logs. Two layers protect this:

1. Handlers never receive body text in the first place -- the orchestrator logs
   character counts, not content (spec section 4.2).
2. This filter is the backstop: it scrubs any record whose message or arguments
   contain a field we consider body-shaped, in case someone adds a careless
   log line later.

The filter cannot inspect what it cannot see, so it is a safety net, not a
substitute for not logging bodies. tests/test_no_body_in_logs.py is the check
that actually verifies the outcome.
"""

import logging
import re

# Keys that carry message content and must never be logged.
SENSITIVE_KEYS = ("body", "snippet", "preview", "text", "draft", "summary", "transcript", "evidence")

_KV = re.compile(
    r"(?i)\b(" + "|".join(SENSITIVE_KEYS) + r")\b(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)

REDACTED = "[REDACTED]"


def _scrub(value):
    if isinstance(value, str):
        return _KV.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
    if isinstance(value, dict):
        return {k: (REDACTED if k.lower() in SENSITIVE_KEYS else _scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(v) for v in value)
    return value


class BodyRedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg = _scrub(record.msg)
        if record.args:
            record.args = _scrub(record.args)
        return True


def install(app):
    """Attach the redacting filter to the app logger and the root logger."""
    f = BodyRedactingFilter()
    app.logger.addFilter(f)
    root = logging.getLogger()
    root.addFilter(f)
    for handler in list(app.logger.handlers) + list(root.handlers):
        handler.addFilter(f)
