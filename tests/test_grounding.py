"""Grounding tests (spec section 8).

"Feed a summary containing a fabricated number and assert it is flagged. Feed a
clean one and assert it is not."

Real functions, real strings, no model and no stub. The false-positive tests
matter as much as the detection tests: a checker that flags every paraphrase
trains users to ignore the warning, which is the same as having no warning.
"""

import pytest

from backend.orchestrator.grounding import (
    check_grounding,
    groundedness_rate,
    verify_evidence,
)

SOURCE = """Subject: Project deadline moved to Friday
From: David Robinson

Can we reschedule our Thursday meeting to Friday at 2pm? I would like to review
the quarterly report together before it goes out to the wider team. The invoice
for $1,250 is still outstanding and 15% of the work remains.
"""


# --- Detection -------------------------------------------------------------


def test_clean_summary_is_not_flagged():
    summary = (
        "David Robinson asks to move the Thursday meeting to Friday at 2pm. "
        "He wants to review the quarterly report before it goes to the team."
    )
    result = check_grounding(summary, SOURCE)
    assert result.grounded is True
    assert result.flags == []


def test_fabricated_number_is_flagged():
    summary = "The meeting moves to Friday and the invoice for $4,500 is outstanding."
    result = check_grounding(summary, SOURCE)
    assert result.grounded is False
    assert any("4,500" in flag.claim for flag in result.flags)


def test_fabricated_percentage_is_flagged():
    result = check_grounding("Around 80% of the work remains.", SOURCE)
    assert result.grounded is False
    assert any("80" in flag.claim for flag in result.flags)


def test_fabricated_time_is_flagged():
    result = check_grounding("The meeting is now at 4pm on Friday.", SOURCE)
    assert result.grounded is False
    assert any("4pm" in flag.claim for flag in result.flags)


def test_fabricated_weekday_is_flagged():
    result = check_grounding("The meeting moves to Monday.", SOURCE)
    assert result.grounded is False
    assert any("monday" in flag.claim.lower() for flag in result.flags)


def test_fabricated_person_is_flagged():
    result = check_grounding("Priya Sharma asked to move the meeting.", SOURCE)
    assert result.grounded is False
    assert any("Priya" in flag.claim for flag in result.flags)


def test_every_flag_carries_a_claim_and_a_reason():
    """Section 3: ungrounded_flags entries are {claim, reason}."""
    result = check_grounding("Meet Priya on Monday at 4pm about the $99 fee.", SOURCE)
    assert len(result.flags) >= 3
    for flag in result.as_api_flags():
        assert set(flag) == {"claim", "reason"}
        assert flag["claim"] and flag["reason"]


def test_a_flagged_claim_is_reported_once():
    result = check_grounding("Monday. Monday again. And Monday.", SOURCE)
    assert len([f for f in result.flags if "monday" in f.claim.lower()]) == 1


# --- Not over-flagging -----------------------------------------------------


def test_numbers_present_in_the_source_are_not_flagged():
    result = check_grounding("The $1,250 invoice is outstanding and 15% remains.", SOURCE)
    assert result.grounded is True


def test_number_formatting_differences_are_not_fabrications():
    """1250 and $1,250.00 are the same claim written three ways."""
    assert check_grounding("The invoice is 1250 dollars.", SOURCE).grounded is True
    assert check_grounding("The invoice is $1,250.00.", SOURCE).grounded is True


def test_equivalent_time_formats_are_not_fabrications():
    for phrasing in ("2pm", "2:00 pm", "2 PM", "14:00"):
        result = check_grounding(f"The meeting is at {phrasing}.", SOURCE)
        assert result.grounded is True, f"{phrasing} was wrongly flagged"


def test_paraphrase_without_new_facts_is_not_flagged():
    result = check_grounding(
        "The sender would like to push the catch-up back by a day so the "
        "report can be looked over first.",
        SOURCE,
    )
    assert result.grounded is True


def test_curly_and_straight_apostrophes_are_the_same_claim():
    source = "The client’s invoice is due."
    assert check_grounding("The client's invoice is due.", source).grounded is True


def test_sentence_initial_capitals_are_not_treated_as_names():
    result = check_grounding("Please review it. Then send it back.", SOURCE)
    assert result.grounded is True


# --- Evidence verification (section 4.3) -----------------------------------


def test_verbatim_evidence_verifies():
    assert verify_evidence("reschedule our Thursday meeting", SOURCE) is True


def test_evidence_verification_ignores_case_and_whitespace():
    assert verify_evidence("RESCHEDULE   our\n Thursday MEETING", SOURCE) is True


def test_fabricated_evidence_does_not_verify():
    assert verify_evidence("the client approved the new budget", SOURCE) is False


def test_paraphrased_evidence_does_not_verify():
    """"Verbatim" has to mean verbatim, or the check proves nothing."""
    assert verify_evidence("asks to move the meeting to Friday", SOURCE) is False


def test_trivially_short_evidence_does_not_verify():
    """A one-word span appears in everything and justifies nothing."""
    assert verify_evidence("the", SOURCE) is False
    assert verify_evidence("", SOURCE) is False


# --- Evaluation hook (section 4.6) -----------------------------------------


def test_groundedness_rate_over_a_batch():
    outputs = [
        {"ungrounded_flags": []},
        {"ungrounded_flags": []},
        {"ungrounded_flags": [{"claim": "$400", "reason": "x"}]},
        {"ungrounded_flags": []},
    ]
    stats = groundedness_rate(outputs)
    assert stats["total"] == 4
    assert stats["grounded"] == 3
    assert stats["flagged"] == 1
    assert stats["rate"] == pytest.approx(0.75)


def test_groundedness_rate_reports_which_entity_backend_ran():
    """An evaluation number is not interpretable without knowing this."""
    assert groundedness_rate([])["entity_backend"] in ("spacy", "heuristic", "unloaded")


def test_groundedness_rate_of_an_empty_batch_is_not_a_crash():
    assert groundedness_rate([])["rate"] == 0.0
