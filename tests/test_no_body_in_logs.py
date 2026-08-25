"""NFR-03: no email body reaches disk or logs.

Spec section 8: "run a full session, grep the logs for known body text, assert
zero matches."

This runs a real session -- login, inbox, summarise, draft, voice -- with
logging attached to a real file on disk at DEBUG level, then greps that file
for distinctive phrases from the fixture bodies and from the model output. The
handler is attached before the app is built so it goes through the same
redaction install path a deployed handler would.

Grepping is a backstop, not the mechanism. The mechanism is that handlers are
never given body text in the first place: the orchestrator logs character
counts (section 4.2), and support.py logs exception frames without exception
messages. This test is what catches it when someone adds a careless log line
later.
"""

import logging
import os

import pytest

from backend.app import create_app
from backend.orchestrator import client as client_module
from tests.conftest import PROMO_EMAIL_ID, WORK_EMAIL_ID, StubLLM

# Distinctive strings from the fixture bodies. Each is rare enough that a match
# in the log means the body itself leaked, not a coincidence.
BODY_PHRASES = [
    "quarterly report",
    "census date",
    "ramen place",
    "Headphones from",
    "supervision meeting",
    "new sign-in to your account",
    "Confirming Thursday at 11am",   # from the quoted history that gets stripped
]

# Model output is derived from the body, so it must not be logged either.
SUMMARY_MARKER = "ZEBRAFISH-SUMMARY-MARKER"
DRAFT_MARKER = "ZEBRAFISH-DRAFT-MARKER"
TRANSCRIPT_MARKER = "ZEBRAFISH-TRANSCRIPT-MARKER"


@pytest.fixture
def log_file(tmp_path):
    """A real file handler on the root logger, attached before the app is built."""
    path = tmp_path / "session.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield path
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(previous_level)


def _run_full_session(config, stub):
    """Login, inbox, summarise, draft and a voice command."""
    app = create_app(config)
    app.config.update(TESTING=True)
    http = app.test_client()

    from tests.conftest import TEST_EMAIL, TEST_PASSWORD

    login = http.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.get_json()['token']}"}

    from backend.adapters.email_source import get_email_source

    stub.queue({"results": [
        {"id": m.id, "category": "Work", "confidence": 0.9, "evidence": m.subject}
        for m in get_email_source(config).list_emails()
    ]})
    assert http.get("/api/inbox", headers=headers).status_code == 200

    stub.queue({
        "summary": [f"{SUMMARY_MARKER} first sentence.", f"{SUMMARY_MARKER} second sentence."],
        "action_items": [],
    })
    assert http.post("/api/summarise", json={"email_id": WORK_EMAIL_ID},
                     headers=headers).status_code == 200

    stub.queue({"draft": f"Hi,\n\n{DRAFT_MARKER}\n\nThanks"})
    assert http.post("/api/draft", json={"email_id": PROMO_EMAIL_ID, "instruction": "decline"},
                     headers=headers).status_code == 200

    stub.queue({"intent": "summarise", "target_reference": "", "confidence": 0.9})
    assert http.post("/api/voice/intent", json={"transcript": TRANSCRIPT_MARKER},
                     headers=headers).status_code == 200

    # An error path too: handlers must not dump the payload on failure.
    assert http.post("/api/summarise", json={"email_id": "no-such-id"},
                     headers=headers).status_code == 404

    return http, headers


@pytest.fixture
def session_log(config, log_file):
    stub = StubLLM()
    client_module.set_client(stub)
    try:
        _run_full_session(config, stub)
    finally:
        client_module.reset_client()
    logging.getLogger().handlers[-1].flush()
    return log_file.read_text(encoding="utf-8")


def test_the_log_actually_captured_the_session(session_log):
    """Guards every assertion below from passing on an empty file."""
    assert "preprocess" in session_log
    assert len(session_log.splitlines()) > 5


def test_no_email_body_text_appears_in_the_log(session_log):
    found = [phrase for phrase in BODY_PHRASES if phrase.lower() in session_log.lower()]
    assert not found, f"email body text leaked into the log: {found}"


def test_no_generated_summary_or_draft_appears_in_the_log(session_log):
    """Model output is derived from the body and is treated the same way."""
    for marker in (SUMMARY_MARKER, DRAFT_MARKER):
        assert marker not in session_log, f"{marker} leaked into the log"


def test_no_voice_transcript_appears_in_the_log(session_log):
    """A transcript is the user speaking; it is content, not metadata."""
    assert TRANSCRIPT_MARKER not in session_log


def test_no_password_or_token_appears_in_the_log(session_log):
    from tests.conftest import TEST_PASSWORD

    assert TEST_PASSWORD not in session_log
    assert "Bearer " not in session_log


def test_character_counts_are_logged_instead(session_log):
    """The useful half of NFR-03: observability without content."""
    assert "chars in" in session_log and "chars out" in session_log


def test_nothing_was_written_to_disk_besides_the_log(config, tmp_path):
    """No cache file, no body dump, no scratch file anywhere under tmp."""
    stub = StubLLM()
    client_module.set_client(stub)
    try:
        _run_full_session(config, stub)
    finally:
        client_module.reset_client()
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [], f"unexpected files written: {written}"


def test_the_redaction_filter_catches_a_careless_log_line(config, log_file):
    """The backstop, tested directly.

    If someone later writes log.info("body=%s", raw), this is what stops it
    reaching disk. It is a safety net and not a substitute for the tests above.
    """
    app = create_app(config)
    with app.app_context():
        logging.getLogger("backend.somewhere").warning(
            "failed to parse body=%s", "the secret quarterly report contents"
        )
    logging.getLogger().handlers[-1].flush()
    contents = log_file.read_text(encoding="utf-8")
    assert "secret quarterly report" not in contents
    assert "[REDACTED]" in contents
