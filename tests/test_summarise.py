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


def test_one_sentence_is_retried_then_returned_rather_than_failing(config, stub_llm):
    """Behaviour change, requested deliberately: a summary is always produced.

    The spec (section 3) said fail loudly after one retry. In use that turned a
    routine model wobble into a dead Summarise button. The model still gets its
    strict attempt and a corrective retry; only after both does the last
    response get returned as-is. Nothing is invented -- one sentence stays one
    sentence -- and it still goes through the grounding check.
    """
    stub_llm.queue(_payload(["Only one sentence here."]), _payload(["Still only one."]))
    result = summarise_email(_email(config), config)
    assert result["summary"] == ["Still only one."]
    assert stub_llm.call_count == 2, "expected exactly one retry"


def test_four_sentences_are_retried_then_truncated(config, stub_llm):
    four = TWO_SENTENCES + ["Third sentence.", "Fourth sentence."]
    stub_llm.queue(_payload(four), _payload(four))
    result = summarise_email(_email(config), config)
    assert len(result["summary"]) == 3
    assert result["summary"] == four[:3], "truncation must keep the leading sentences"
    assert stub_llm.call_count == 2


def test_a_valid_retry_succeeds(config, stub_llm):
    stub_llm.queue(_payload(["Only one."]), _payload())
    result = summarise_email(_email(config), config)
    assert len(result["summary"]) == 2
    assert stub_llm.call_count == 2


def test_a_short_summary_is_never_padded(config, stub_llm):
    """Truncating is acceptable; padding is not.

    Dropping a fourth sentence discards the model's content. Padding one
    sentence to two would mean *writing* the second, which is fabrication --
    exactly what the grounding layer exists to prevent. So repair only ever
    removes.
    """
    stub_llm.queue(_payload(["Only one."]), _payload(["Only one."]))
    result = summarise_email(_email(config), config)
    assert result["summary"] == ["Only one."], "a short summary must not be padded"


def test_failure_is_loud_not_an_empty_summary(config, stub_llm):
    stub_llm.queue(_payload([]), _payload([]))
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)


def test_blank_strings_do_not_count_as_sentences(config, stub_llm):
    """Whitespace entries are dropped, so this really is a one-sentence summary
    and must not be inflated to two by counting the blank."""
    stub_llm.queue(_payload(["A real sentence.", "   ", ""]),
                   _payload(["A real sentence.", "  "]))
    result = summarise_email(_email(config), config)
    assert result["summary"] == ["A real sentence."]


# --- Action items (section 4.4) --------------------------------------------


def test_action_items_carry_a_source_sentence(config, stub_llm):
    stub_llm.queue(_payload(action_items=[{"text": "Confirm Friday 2pm", "source_sentence": 1}]))
    items = summarise_email(_email(config), config)["action_items"]
    assert items == [{"text": "Confirm Friday 2pm", "source_sentence": 1}]


def test_an_empty_action_item_list_is_valid(config, stub_llm):
    """Section 3: never invent one to fill the array."""
    stub_llm.queue(_payload(action_items=[]))
    assert summarise_email(_email(config), config)["action_items"] == []


def test_source_sentence_out_of_range_is_retried_then_clamped(config, stub_llm):
    """An index pointing nowhere breaks traceability, so it gets a strict
    attempt and a corrective retry first. On the final pass it is clamped to
    the last real sentence rather than dropping a genuine action item."""
    bad = _payload(action_items=[{"text": "Do something", "source_sentence": 7}])
    stub_llm.queue(bad, bad)
    result = summarise_email(_email(config), config)
    assert result["action_items"][0]["source_sentence"] == len(result["summary"])
    assert stub_llm.call_count == 2


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
    # `provenance` is an approved addition to the documented shape: offsets
    # locating the source passage behind each summary sentence.
    assert set(result) == {
        "email_id", "summary", "action_items", "grounded", "ungrounded_flags",
        "provenance",
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


# --- The failure that prompted the change ----------------------------------


def test_multiple_sentences_in_one_array_element_are_re_split(config, stub_llm):
    """The real-world fault behind "summary had 1 sentences".

    The model returned a correct two-sentence summary packed into a single
    array element. Counting elements called that one sentence and failed the
    request. Re-splitting reads what the model actually wrote, so this now
    succeeds on the FIRST attempt with no retry.
    """
    stub_llm.queue(_payload(["The meeting moved to Friday at 2pm. The report is attached."]))
    result = summarise_email(_email(config), config)
    assert result["summary"] == [
        "The meeting moved to Friday at 2pm.",
        "The report is attached.",
    ]
    assert stub_llm.call_count == 1, "re-splitting should not need a retry"


def test_an_abbreviation_is_not_split_mid_sentence(config, stub_llm):
    """Splitting must not tear "Dr. Ford" or "2 p.m." in half."""
    stub_llm.queue(_payload(["Dr. Ford replied. The meeting is at 2 p.m. on Friday."]))
    result = summarise_email(_email(config), config)
    assert result["summary"][0] == "Dr. Ford replied."
    assert result["summary"][1] == "The meeting is at 2 p.m. on Friday."


def test_the_retry_prompt_states_the_fault(config, stub_llm):
    """A retry that re-sends the identical prompt wastes the only retry there
    is; the second attempt must say what was wrong."""
    stub_llm.queue(_payload(["Only one."]), _payload())
    summarise_email(_email(config), config)
    second_prompt = stub_llm.calls[1]["user"]
    assert "rejected" in second_prompt.lower()


def test_an_unusable_response_still_fails_loudly(config, stub_llm):
    """Repair fixes shape, not absence. With nothing to repair, it must fail."""
    stub_llm.queue({"summary": [], "action_items": []}, {"summary": [], "action_items": []})
    with pytest.raises(SummaryValidationError):
        summarise_email(_email(config), config)
