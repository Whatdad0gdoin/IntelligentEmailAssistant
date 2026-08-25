"""Draft tests (FR-03, spec sections 4.5 and 8).

Includes the negative send test. "Assert no send call is reachable without the
Approve click" has a backend half and a frontend half; this file covers the
backend half, and it covers it structurally rather than by trying every URL:
there is no send route in the URL map, no mail-sending library imported
anywhere in the backend, and no outbound address in the draft response.

The frontend half -- that the Approve control gates the path -- belongs with
the Draft view and is not built yet. See the README build table.
"""

import os
import re

import pytest

from backend.adapters.email_source import get_email_source
from backend.orchestrator.draft import DraftValidationError, draft_reply
from tests.conftest import WORK_EMAIL_ID

BACKEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"
)


def _email(config):
    message = get_email_source(config).get_email(WORK_EMAIL_ID)
    assert message is not None
    return message


CLEAN_DRAFT = (
    "Hi David,\n\nFriday at 2pm works for me. I will review the quarterly "
    "report beforehand.\n\nThanks"
)


# --- The negative send test ------------------------------------------------


def test_no_send_route_exists(app):
    """Section 3 states there is no send endpoint in this build."""
    paths = [str(rule).lower() for rule in app.url_map.iter_rules()]
    offenders = [p for p in paths if re.search(r"send|deliver|smtp|outbox|mail/out", p)]
    assert not offenders, f"a send-shaped route exists: {offenders}"


def test_no_mail_sending_library_is_imported_anywhere_in_the_backend():
    """A send path cannot exist if nothing in the backend can send mail.

    Checked across the whole backend rather than one module, because the point
    is that there is no such capability at all -- not that one file avoids it.
    """
    pattern = re.compile(r"^\s*(?:import|from)\s+(smtplib|email\.smtp|yagmail|sendgrid)", re.M)
    offenders = []
    for root, _, files in os.walk(BACKEND_DIR):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as handle:
                if pattern.search(handle.read()):
                    offenders.append(path)
    assert not offenders, f"mail-sending capability found in: {offenders}"


def test_the_draft_response_carries_text_and_nothing_actionable(config, stub_llm):
    """No recipient, no send token, no URL the frontend could POST to."""
    stub_llm.queue({"draft": CLEAN_DRAFT})
    result = draft_reply(_email(config), None, config)
    assert set(result) == {"draft", "grounded", "ungrounded_flags"}
    serialised = str(result).lower()
    for forbidden in ("send", "recipient", "to_address", "smtp", "http://", "https://"):
        assert forbidden not in serialised


def test_drafting_is_not_sending(config, stub_llm):
    """The route returns text; the user decides what happens to it."""
    stub_llm.queue({"draft": CLEAN_DRAFT})
    result = draft_reply(_email(config), None, config)
    assert result["draft"] == CLEAN_DRAFT


# --- Grounding (section 4.5) -----------------------------------------------


def test_a_clean_draft_is_marked_grounded(config, stub_llm):
    stub_llm.queue({"draft": CLEAN_DRAFT})
    result = draft_reply(_email(config), None, config)
    assert result["grounded"] is True
    assert result["ungrounded_flags"] == []


def test_an_invented_commitment_is_flagged(config, stub_llm):
    """The failure mode that matters: agreeing to something never discussed."""
    stub_llm.queue({"draft": "Hi David,\n\nI can do Monday at 9am instead.\n\nThanks"})
    result = draft_reply(_email(config), None, config)
    assert result["grounded"] is False
    claims = " ".join(flag["claim"].lower() for flag in result["ungrounded_flags"])
    assert "monday" in claims


def test_an_invented_amount_is_flagged(config, stub_llm):
    stub_llm.queue({"draft": "Hi David,\n\nThe $12,000 figure looks right.\n\nThanks"})
    result = draft_reply(_email(config), None, config)
    assert result["grounded"] is False
    assert any("12,000" in flag["claim"] for flag in result["ungrounded_flags"])


def test_flags_carry_a_claim_and_a_reason(config, stub_llm):
    """Section 3: ungrounded_flags is [{claim, reason}]."""
    stub_llm.queue({"draft": "Hi David,\n\nMonday at 9am suits me.\n\nThanks"})
    for flag in draft_reply(_email(config), None, config)["ungrounded_flags"]:
        assert set(flag) == {"claim", "reason"}


def test_a_fact_from_the_user_instruction_is_not_a_fabrication(config, stub_llm):
    """The user is allowed to introduce facts. The model is not."""
    stub_llm.queue({"draft": "Hi David,\n\nI can do Monday at 9am instead.\n\nThanks"})
    result = draft_reply(
        _email(config), "tell him Monday at 9am suits me better", config
    )
    assert result["grounded"] is True


def test_a_flagged_draft_is_still_returned(config, stub_llm):
    """Section 5.4 shows the flags above the textarea; it needs the draft too."""
    stub_llm.queue({"draft": "Hi David,\n\nMonday at 9am suits me.\n\nThanks"})
    result = draft_reply(_email(config), None, config)
    assert result["draft"]
    assert result["grounded"] is False


# --- Validation ------------------------------------------------------------


def test_an_empty_draft_is_retried_once_then_fails(config, stub_llm):
    stub_llm.queue({"draft": ""}, {"draft": "   "})
    with pytest.raises(DraftValidationError):
        draft_reply(_email(config), None, config)
    assert stub_llm.call_count == 2


def test_a_valid_retry_succeeds(config, stub_llm):
    stub_llm.queue({"draft": ""}, {"draft": CLEAN_DRAFT})
    assert draft_reply(_email(config), None, config)["draft"] == CLEAN_DRAFT
    assert stub_llm.call_count == 2


def test_an_overlong_instruction_is_truncated_not_rejected(config, stub_llm):
    stub_llm.queue({"draft": CLEAN_DRAFT})
    draft_reply(_email(config), "x" * 5000, config)
    assert len(stub_llm.calls[0]["user"]) < 5000


def test_quoted_history_is_not_sent_to_the_model(config, stub_llm):
    stub_llm.queue({"draft": CLEAN_DRAFT})
    draft_reply(_email(config), None, config)
    prompt = stub_llm.calls[0]["user"]
    assert "11am" not in prompt, "the stripped reply chain reached the prompt"


def test_drafts_are_not_cached(config, stub_llm):
    """Same email, different instruction, must be a different call."""
    stub_llm.queue({"draft": CLEAN_DRAFT}, {"draft": CLEAN_DRAFT})
    draft_reply(_email(config), "accept", config, user_email="u@example.com")
    draft_reply(_email(config), "decline", config, user_email="u@example.com")
    assert stub_llm.call_count == 2
