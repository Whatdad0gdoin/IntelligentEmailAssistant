"""Log redaction (NFR-03).

Email bodies must never reach disk or logs. Two layers protect this:

1. Handlers never receive body text in the first place -- the orchestrator logs
   character counts, not content (spec section 4.2), and routes log exception
   frames without exception messages (routes/support.py).
2. This filter is the backstop: it scrubs any record whose message, arguments
   or traceback contain a field we consider body-shaped, in case someone adds a
   careless log line later.

The filter cannot inspect what it cannot see, so it is a safety net, not a
substitute for not logging bodies. tests/test_no_body_in_logs.py is the check
that actually verifies the outcome, by running a real session and grepping a
real log file.

Implementation note. The obvious version of this -- scrub `record.msg` before
formatting -- does not work, and failed in three ways worth recording so the
mistake is not reintroduced:

  * `log.info("body=%s", value)` has the sensitive data in `record.args`, not
    in `record.msg`. Scrubbing the format string turned "body=%s" into
    "body=[REDACTED]", which then raised "not all arguments converted" at
    format time and lost the line entirely.
  * On an already-rendered string, a `\\S+` value pattern redacted only the
    first word: "body=the secret report" became "body=[REDACTED] secret
    report".
  * A dict rendered as "{'body': 'secret'}" was not matched at all, because the
    quote sits between the key and the colon.

So the record is rendered first and the *result* is scrubbed. Unquoted values
are redacted to end of line: over-redacting a log line is a cost worth paying
against under-redacting an email.
"""

import logging
import re
import traceback

# Keys that carry message content and must never be logged.
SENSITIVE_KEYS = (
    "body", "snippet", "preview", "text", "draft", "summary", "transcript",
    "evidence", "content", "message_body", "password", "token", "authorization",
)

_KEYS = "|".join(SENSITIVE_KEYS)

# key = "quoted value"  /  key: 'quoted value'
_QUOTED = re.compile(
    r"(?i)([\"']?\b(?:" + _KEYS + r")\b[\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*')"
)
# key = anything to end of line
_UNQUOTED = re.compile(
    r"(?i)([\"']?\b(?:" + _KEYS + r")\b[\"']?\s*[=:]\s*)([^\n]+)"
)

REDACTED = "[REDACTED]"


def scrub(text):
    """Redact body-shaped key/value pairs in an already-rendered string."""
    if not text:
        return text
    text = _QUOTED.sub(lambda m: m.group(1) + REDACTED, text)
    return _UNQUOTED.sub(lambda m: m.group(1) + REDACTED, text)


def scrub_traceback(exc_info):
    """Render a traceback keeping the frames but dropping exception messages.

    An exception message is the single most likely place for email content to
    escape: a parse error raised mid-body carries the fragment it choked on. So
    the type is kept and the message is not -- file, line and function are what
    locate a bug anyway.
    """
    lines = []
    for line in traceback.format_exception(*exc_info):
        for part in line.rstrip("\n").split("\n"):
            stripped = part.strip()
            if not stripped:
                continue
            if part.startswith("  ") or stripped.startswith("Traceback"):
                # A frame line, or the header. No user data in either.
                lines.append(part)
                continue
            # "SomeError: some message" -- keep the type, drop the message.
            exception_type = stripped.split(":", 1)[0]
            lines.append(f"{exception_type}: {REDACTED}")
    return "\n".join(lines)


class BodyRedactingFilter(logging.Filter):
    def filter(self, record):
        try:
            rendered = record.getMessage()
        except Exception:
            # A broken format string must not take down the request.
            rendered = str(record.msg)

        record.msg = scrub(rendered)
        record.args = ()

        if record.exc_info:
            record.exc_text = scrub(scrub_traceback(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = scrub(record.exc_text)

        return True


def install(app):
    """Attach the redacting filter to the app logger and the root logger.

    Attached to the loggers rather than only to their handlers so a handler
    added later -- by a deployment, or by a test -- is still covered.
    """
    log_filter = BodyRedactingFilter()
    app.logger.addFilter(log_filter)
    root = logging.getLogger()
    root.addFilter(log_filter)
    for handler in list(app.logger.handlers) + list(root.handlers):
        handler.addFilter(log_filter)
