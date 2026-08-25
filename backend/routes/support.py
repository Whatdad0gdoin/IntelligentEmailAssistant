"""Shared route plumbing.

Routes in this project do four things and no more: read the request, call an
orchestrator or adapter, shape the response, and translate a failure into a
status code. Anything resembling a model call, a prompt or a grounding rule
belongs in backend/orchestrator, not here (spec rule 4).

The error translation lives in one decorator so every route reports the same
failure the same way, and so no handler can accidentally return a 200 with an
empty body when the orchestrator raised.
"""

import functools
import logging
import traceback

from flask import current_app, g, jsonify, request

from backend.adapters.email_source import EmailSourceError
from backend.orchestrator.budget import BudgetExceeded
from backend.orchestrator.client import LLMSchemaError, LLMUnavailable
from backend.orchestrator.draft import DraftValidationError
from backend.orchestrator.draft import EmptyEmailError as DraftEmptyEmailError
from backend.orchestrator.summarise import EmptyEmailError, SummaryValidationError

log = logging.getLogger(__name__)


def config():
    return current_app.config["APP_CONFIG"]


def current_user():
    return getattr(g, "user_email", None)


def session_key():
    """Identifies one login, for the per-session request cap."""
    return getattr(g, "session_key", None)


class BadRequest(Exception):
    """The request body was missing something the route needs."""


class EmailNotFound(Exception):
    """No message with that id in the source mailbox."""


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Expected a JSON object.")
    return body


def required_string(body, field, max_length=512):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"'{field}' is required.")
    if len(value) > max_length:
        raise BadRequest(f"'{field}' is too long.")
    return value.strip()


# Orchestrator failure -> HTTP status. Ordered most specific first.
#
# Note what is *not* here: no branch returns a success shape on failure. A
# route that cannot produce a real summary returns an error, never an empty
# summary that the UI would render as though the model had said nothing.
_ERROR_STATUS = (
    (BadRequest, 400),
    (EmailNotFound, 404),
    (BudgetExceeded, 429),
    (EmptyEmailError, 422),
    (DraftEmptyEmailError, 422),
    (SummaryValidationError, 502),
    (DraftValidationError, 502),
    (LLMSchemaError, 502),
    (LLMUnavailable, 503),
    (EmailSourceError, 503),
)


def handle_errors(view):
    """Translate orchestrator and adapter failures into JSON error responses."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except Exception as exc:
            for error_type, status in _ERROR_STATUS:
                if isinstance(exc, error_type):
                    # These messages are written for a user to read and contain
                    # no email content, so they are safe to return and to log.
                    log.info("%s -> %d (%s)", request.path, status, type(exc).__name__)
                    return jsonify({"error": str(exc)}), status
            # Unrecognised. Deliberately not log.exception(): a traceback
            # includes the exception's own message, and an unexpected error
            # raised mid-parse can carry a fragment of the email in it
            # (a KeyError on parsed content, for instance). NFR-03 says that
            # must not reach a log, so the frames are logged without it --
            # file, line and function are what locate the bug anyway.
            frames = " <- ".join(
                f"{frame.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:"
                f"{frame.lineno} in {frame.name}"
                for frame in reversed(traceback.extract_tb(exc.__traceback__)[-4:])
            )
            log.error("Unhandled %s in %s at %s", type(exc).__name__, request.path, frames)
            return jsonify({"error": "Something went wrong. Please try again."}), 500

    return wrapper
