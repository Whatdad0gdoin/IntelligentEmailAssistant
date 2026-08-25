"""Voice intent tests (FR-05, spec sections 6.3 and 8).

Three separate things are tested here, and it is worth being clear about which
is which:

1. Target resolution -- deterministic, no model, always runs. This is the part
   that decides *which email* an action applies to, and rule 5 keeps it out of
   the model entirely.
2. Backend handling of a model response -- stubbed, always runs.
3. The 30-transcript accuracy criterion -- needs the real model, so it is
   SKIPPED unless RUN_LLM_EVAL=1 and a key is configured. A skip, not a pass:
   asserting 90% accuracy against a stub would be asserting that the stub
   returns what the stub was told to return.
"""

import csv
import os

import pytest

from backend.orchestrator.intent import classify_intent, resolve_target
from backend.orchestrator.schemas import INTENTS

EVAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "data"
)
GRADED_CSV = os.path.join(EVAL_DIR, "voice_intents.csv")
UNKNOWN_CSV = os.path.join(EVAL_DIR, "voice_intents_unknown.csv")

CANDIDATES = [
    {"id": "work-1", "sender_name": "David Robinson", "subject": "Project deadline moved to Friday"},
    {"id": "studies-2", "sender_name": "Monash Enrolments", "subject": "Semester 2 unit registration now open"},
    {"id": "personal-3", "sender_name": "Sarah Chen", "subject": "Dinner this weekend?"},
    {"id": "promo-4", "sender_name": "TechDeals", "subject": "48-hour flash sale"},
]


def _rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("transcript")]


# --- Target resolution: deterministic, no model ----------------------------


def test_sender_first_name_resolves():
    assert resolve_target("", "summarise the email from sarah", CANDIDATES) == "personal-3"


def test_sender_full_name_resolves():
    assert resolve_target("", "read the one from david robinson", CANDIDATES) == "work-1"


def test_subject_words_resolve():
    assert resolve_target("", "summarise the dinner email", CANDIDATES) == "personal-3"


def test_sender_outranks_a_subject_word():
    """People name mail by who sent it far more often than by what it says."""
    assert resolve_target("", "read the flash sale email from sarah", CANDIDATES) == "personal-3"


def test_recency_phrase_resolves_to_the_newest():
    """Candidates arrive newest first, as the adapter sorts them."""
    assert resolve_target("", "summarise the latest email", CANDIDATES) == "work-1"
    assert resolve_target("", "read the most recent one", CANDIDATES) == "work-1"


def test_an_unresolvable_reference_returns_none():
    assert resolve_target("", "summarise the email from bob", CANDIDATES) is None


def test_an_ambiguous_reference_returns_none_rather_than_guessing():
    """Two equally good matches means the user has to say which."""
    candidates = [
        {"id": "a", "sender_name": "Sarah Chen", "subject": "Dinner"},
        {"id": "b", "sender_name": "Sarah Chen", "subject": "Lunch"},
    ]
    assert resolve_target("", "read the email from sarah", candidates) is None


def test_a_title_alone_does_not_identify_anyone():
    candidates = [
        {"id": "a", "sender_name": "Dr Amelia Ford", "subject": "Feedback"},
        {"id": "b", "sender_name": "Dr Peter Lee", "subject": "Timetable"},
    ]
    assert resolve_target("", "read the email from the doctor", candidates) is None


def test_no_candidates_means_no_target():
    assert resolve_target("", "summarise the email from sarah", []) is None


def test_the_model_never_supplies_the_id():
    """Rule 5: ids are parsed data.

    Even if a model returned a real-looking id in target_reference, resolution
    matches it against sender names and subjects -- so an id it invented cannot
    become the answer.
    """
    assert resolve_target("work-1", "do the thing", CANDIDATES) is None


# --- Backend handling of a model response ----------------------------------


def _intent_response(intent="summarise", reference="the one from sarah", confidence=0.93):
    return {"intent": intent, "target_reference": reference, "confidence": confidence}


def test_response_matches_the_documented_contract(config, stub_llm):
    stub_llm.queue(_intent_response())
    result = classify_intent("summarise the email from sarah", config, candidates=CANDIDATES)
    assert set(result) == {"intent", "target_email_id", "confidence"}
    assert result["intent"] == "summarise"
    assert result["target_email_id"] == "personal-3"


def test_unknown_is_a_valid_outcome_and_is_passed_through(config, stub_llm):
    """Section 6.3: do not force a guess."""
    stub_llm.queue(_intent_response(intent="unknown", reference="", confidence=0.2))
    result = classify_intent("whats the weather like", config, candidates=CANDIDATES)
    assert result["intent"] == "unknown"
    assert result["target_email_id"] is None


def test_low_confidence_is_reported_not_suppressed(config, stub_llm):
    """The UI applies the threshold and asks the user; the backend reports."""
    stub_llm.queue(_intent_response(confidence=0.31))
    result = classify_intent("mumble mumble", config, candidates=CANDIDATES)
    assert result["confidence"] == 0.31
    assert config.intent_confidence_threshold > 0.31


def test_an_intent_outside_the_enum_becomes_unknown(config, stub_llm):
    stub_llm.queue(_intent_response(intent="delete_everything"))
    assert classify_intent("do something", config)["intent"] == "unknown"


def test_an_empty_transcript_costs_no_api_call(config, stub_llm):
    result = classify_intent("   ", config, candidates=CANDIDATES)
    assert result == {"intent": "unknown", "target_email_id": None, "confidence": 0.0}
    assert stub_llm.call_count == 0


def test_no_target_is_resolved_for_an_unknown_intent(config, stub_llm):
    """Nothing is dispatched, so naming a target would be misleading."""
    stub_llm.queue(_intent_response(intent="unknown", reference="the one from sarah"))
    assert classify_intent("...", config, candidates=CANDIDATES)["target_email_id"] is None


# --- The dataset itself (always checked) -----------------------------------


def test_the_acceptance_set_has_exactly_thirty_transcripts():
    """Section 6.3 specifies 30 commands."""
    assert len(_rows(GRADED_CSV)) == 30


def test_the_acceptance_set_covers_the_three_intents():
    counts = {}
    for row in _rows(GRADED_CSV):
        counts[row["expected_intent"]] = counts.get(row["expected_intent"], 0) + 1
    assert set(counts) == {"summarise", "read", "draft"}
    assert all(count >= 8 for count in counts.values()), counts


def test_every_label_in_the_dataset_is_a_real_intent():
    for path in (GRADED_CSV, UNKNOWN_CSV):
        for row in _rows(path):
            assert row["expected_intent"] in INTENTS, row


def test_no_duplicate_transcripts():
    """A duplicate would inflate the score without testing anything new."""
    transcripts = [row["transcript"] for row in _rows(GRADED_CSV)]
    assert len(set(transcripts)) == len(transcripts)


# --- The accuracy criterion (needs the real model) -------------------------

_LIVE_EVAL = os.environ.get("RUN_LLM_EVAL") == "1" and os.environ.get("OPENAI_API_KEY")

_SKIP_REASON = (
    "Needs the real model. Run with RUN_LLM_EVAL=1 and OPENAI_API_KEY set, or "
    "use `python -m eval.intent_harness` for the full report. This is skipped "
    "rather than stubbed on purpose: a stubbed accuracy figure would measure "
    "the stub, not the classifier."
)


@pytest.mark.skipif(not _LIVE_EVAL, reason=_SKIP_REASON)
def test_thirty_transcripts_dispatch_at_or_above_ninety_percent():
    from backend.config import Config

    live_config = Config(require_llm=True)
    rows = _rows(GRADED_CSV)
    correct = sum(
        1 for row in rows
        if classify_intent(row["transcript"], live_config)["intent"] == row["expected_intent"]
    )
    rate = correct / len(rows)
    assert rate >= 0.90, f"{correct}/{len(rows)} = {rate:.1%}, below the 90% criterion"
