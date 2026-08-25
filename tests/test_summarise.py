"""Summarisation tests (FR-01, spec sections 3, 4.4 and 8).

The sentence count is the interesting case. The spec requires it to be enforced
programmatically, retried once, then failed loudly -- so these tests assert
that a bad count is *not* quietly padded or trimmed into shape, and that a
second failure produces an error rather than a half-summary.
"""

import pytest

from backend.adapters.email_source import get_email_source
from backend.orchestrator.summarise import (
    EmptyEmailError,
    SummaryValidationError,
    summarise_email,
)
from tests.conftest import WORK_EMAIL_ID

TWO_SENTENCES = [
    "David Robinson asks to move the Thursday meeting to Friday at 2pm.",
    "He wants to review the quarterly report together beforehand.",
]


def _email(config, email_id=WORK_EMAIL_ID):
    message = get_email_source(config).get_email(email_id)
    assert message is not None, f"fixture {email_id} missing"
    return message


def _payload(summary=None, action_items=None):
    return {
        "summary": TWO_SENTENCES if summary is None else summary,
        "action_items": [] if action_items is None else action_items,
    }


# --- Sentence count (section 3) --------------------------------------------


def test_two_sentences_are_accepted(config, stub_llm):
    stub_llm.queue(_payload())
    assert len(summarise_email(_email(config), config)["summary"]) == 2


def test_three_sentences_are_accepted(config, stub_llm):
    stub_llm.queue(_payload(TWO_SENTENCES + ["The draft is attached for review."]))
    assert len(summarise_email(_email(config), config)["summary"]) == 3


def test_one_sentence_is_retried_once_then_fails(config, stub_llm):
    stub_llm.queue(_payload(["Only one sentence here."]), _payload(["Still only one."]))
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)
    assert stub_llm.call_count == 2, "expected exactly one retry"


def test_four_sentences_are_retried_once_then_fail(config, stub_llm):
    four = TWO_SENTENCES + ["Third sentence.", "Fourth sentence."]
    stub_llm.queue(_payload(four), _payload(four))
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)
    assert stub_llm.call_count == 2


def test_a_valid_retry_succeeds(config, stub_llm):
    stub_llm.queue(_payload(["Only one."]), _payload())
    result = summarise_email(_email(config), config)
    assert len(result["summary"]) == 2
    assert stub_llm.call_count == 2


def test_a_bad_count_is_never_padded_or_trimmed_into_shape(config, stub_llm):
    """Trimming 5 sentences to 3 would silently discard content.

    Padding 1 to 2 would mean inventing the second sentence. Neither is an
    acceptable way to satisfy the rule, so failure is the only outcome left.
    """
    five = [f"Sentence number {n}." for n in range(5)]
    stub_llm.queue(_payload(five), _payload(five))
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)


def test_failure_is_loud_not_an_empty_summary(config, stub_llm):
    stub_llm.queue(_payload([]), _payload([]))
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)


def test_blank_strings_do_not_count_as_sentences(config, stub_llm):
    stub_llm.queue(_payload(["A real sentence.", "   ", ""]),
                   _payload(["A real sentence.", "  "]))
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)


# --- Action items (section 4.4) --------------------------------------------


def test_action_items_carry_a_source_sentence(config, stub_llm):
    stub_llm.queue(_payload(action_items=[{"text": "Confirm Friday 2pm", "source_sentence": 1}]))
    items = summarise_email(_email(config), config)["action_items"]
    assert items == [{"text": "Confirm Friday 2pm", "source_sentence": 1}]


def test_an_empty_action_item_list_is_valid(config, stub_llm):
    """Section 3: never invent one to fill the array."""
    stub_llm.queue(_payload(action_items=[]))
    assert summarise_email(_email(config), config)["action_items"] == []


def test_source_sentence_out_of_range_is_rejected(config, stub_llm):
    """An index pointing nowhere breaks the traceability the field is for."""
    bad = _payload(action_items=[{"text": "Do something", "source_sentence": 7}])
    stub_llm.queue(bad, bad)
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)


def test_source_sentence_zero_is_rejected(config, stub_llm):
    """The index is 1-based, per the contract in section 3."""
    bad = _payload(action_items=[{"text": "Do something", "source_sentence": 0}])
    stub_llm.queue(bad, bad)
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)


# --- Grounding (section 4.4) -----------------------------------------------


def test_a_clean_summary_is_marked_grounded(config, stub_llm):
    stub_llm.queue(_payload())
    result = summarise_email(_email(config), config)
    assert result["grounded"] is True
    assert result["ungrounded_flags"] == []


def test_a_fabricated_claim_is_flagged_but_still_returned(config, stub_llm):
    """Section 4.4: return it marked unverified. Do not drop it, do not hide it."""
    stub_llm.queue(_payload([
        "David Robinson asks to move the meeting to Friday at 2pm.",
        "He also confirmed the $8,000 budget was approved on Monday.",
    ]))
    result = summarise_email(_email(config), config)
    assert result["grounded"] is False
    assert len(result["summary"]) == 2, "the summary is still returned"
    claims = " ".join(flag["claim"] for flag in result["ungrounded_flags"])
    assert "8,000" in claims


def test_action_item_text_is_checked_for_grounding_too(config, stub_llm):
    stub_llm.queue(_payload(
        action_items=[{"text": "Pay the $9,999 invoice by Monday", "source_sentence": 1}]
    ))
    result = summarise_email(_email(config), config)
    assert result["grounded"] is False


def test_quoted_history_is_not_a_grounding_source(config, stub_llm):
    """A claim only found in the stripped reply chain is not grounded.

    The model never saw that text, so a claim matching it did not come from
    there -- and the check must not accept it as though it did.
    """
    stub_llm.queue(_payload([
        "The sender confirms the meeting is at 11am on Thursday.",
        "The report will be reviewed beforehand.",
    ]))
    result = summarise_email(_email(config), config)
    assert result["grounded"] is False
    assert any("11am" in flag["claim"] for flag in result["ungrounded_flags"])


# --- Shape, caching and edge cases -----------------------------------------


def test_response_matches_the_documented_contract(config, stub_llm):
    stub_llm.queue(_payload())
    result = summarise_email(_email(config), config)
    assert set(result) == {
        "email_id", "summary", "action_items", "grounded", "ungrounded_flags",
    }
    assert result["email_id"] == WORK_EMAIL_ID


def test_a_re_read_costs_zero_api_calls(config, stub_llm):
    """Section 4.1: cache summaries keyed on email_id."""
    stub_llm.queue(_payload())
    first = summarise_email(_email(config), config, user="u@example.com")
    second = summarise_email(_email(config), config, user="u@example.com")
    assert first == second
    assert stub_llm.call_count == 1


def test_the_summary_cache_does_not_leak_between_users(config, stub_llm):
    stub_llm.queue(_payload(), _payload(["A different summary.", "With two sentences."]))
    summarise_email(_email(config), config, user="a@example.com")
    summarise_email(_email(config), config, user="b@example.com")
    assert stub_llm.call_count == 2


def test_an_email_with_no_readable_text_fails_clearly(config, stub_llm):
    class Empty:
        id = "empty-1"
        subject = ""
        sender_name = ""
        raw_body = "> only quoted text\n> more quoted text"
        is_html = False

    with pytest.raises(EmptyEmailError):
        summarise_email(Empty(), config)
    assert stub_llm.call_count == 0, "no point paying for a call with nothing to summarise"
