"""Voice intent tests (FR-05, spec sections 6.3 and 8).

Four separate things are tested here, and it is worth being clear about which
is which:

1. Target resolution -- deterministic, no model, always runs. This is the part
   that decides *which email* an action applies to, and rule 5 keeps it out of
   the model entirely.
2. Backend handling of a model response -- stubbed, always runs.
3. The transcript sets and the harness that measures them -- offline, always
   runs. These hold the properties the published figures rest on: the 30
   acceptance transcripts, a held-out set that is disjoint from them and
   balanced, and a harness that still measures the original files by default.
4. The 90% accuracy criterion -- needs the real model, so it is SKIPPED
   unless RUN_LLM_EVAL=1 and a key is configured. A skip, not a pass:
   asserting 90% accuracy against a stub would be asserting that the stub
   returns what the stub was told to return.
"""

import csv
import os
import re
import subprocess
import sys
from collections import Counter

import pytest

from backend.orchestrator.intent import classify_intent, resolve_target
from backend.orchestrator.schemas import INTENTS
from eval import intent_harness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(ROOT, "eval", "data")
GRADED_CSV = os.path.join(EVAL_DIR, "voice_intents.csv")
UNKNOWN_CSV = os.path.join(EVAL_DIR, "voice_intents_unknown.csv")
HELDOUT_CSV = os.path.join(EVAL_DIR, "voice_intents_heldout.csv")
HELDOUT_UNKNOWN_CSV = os.path.join(EVAL_DIR, "voice_intents_heldout_unknown.csv")

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
    """Candidates arrive newest first: the frontend sends them sorted, and the
    route re-sorts by received_at when supplied."""
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
    for path in (GRADED_CSV, UNKNOWN_CSV, HELDOUT_CSV, HELDOUT_UNKNOWN_CSV):
        for row in _rows(path):
            assert row["expected_intent"] in INTENTS, row


def test_no_duplicate_transcripts():
    """A duplicate would inflate the score without testing anything new."""
    transcripts = [row["transcript"] for row in _rows(GRADED_CSV)]
    assert len(set(transcripts)) == len(transcripts)


# --- The held-out set (always checked) -------------------------------------
#
# Written and frozen before INTENT_SYSTEM was rewritten to fix the misses on
# the 30 above, so the rewrite can be measured on transcripts it was not tuned
# against (FIXES.md item 5, route b). These tests hold the properties that
# claim depends on; they say nothing about how realistic the rows are.


def test_the_heldout_set_is_balanced_across_the_three_intents():
    """Equal support, so a weak intent cannot hide inside the headline."""
    counts = Counter(row["expected_intent"] for row in _rows(HELDOUT_CSV))
    assert set(counts) == {"summarise", "read", "draft"}
    assert len(set(counts.values())) == 1, counts
    assert min(counts.values()) >= 15, counts


def test_the_heldout_probes_are_all_out_of_scope():
    rows = _rows(HELDOUT_UNKNOWN_CSV)
    assert len(rows) >= 12
    assert {row["expected_intent"] for row in rows} == {"unknown"}


def test_the_heldout_sets_share_no_transcript_with_the_original_sets():
    """A shared row would be one the prompt was fixed against -- the thing a
    held-out set exists to exclude -- and a repeated row would count twice."""
    original = {row["transcript"] for path in (GRADED_CSV, UNKNOWN_CSV) for row in _rows(path)}
    heldout = [
        row["transcript"] for path in (HELDOUT_CSV, HELDOUT_UNKNOWN_CSV) for row in _rows(path)
    ]
    assert len(set(heldout)) == len(heldout), "a transcript appears twice in the held-out sets"
    assert not original & set(heldout)


def test_the_heldout_sets_are_written_like_the_acceptance_set():
    """Same columns and the same surface form -- lowercase words, no
    punctuation -- so the two sets differ in what was said, not in how it was
    typed, and their figures can be compared."""
    for path in (HELDOUT_CSV, HELDOUT_UNKNOWN_CSV):
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == ["transcript", "expected_intent"], path
            for row in reader:
                assert re.fullmatch(r"[a-z]+( [a-z]+)*", row["transcript"]), row


# --- The harness (offline) -------------------------------------------------


def test_the_harness_still_measures_the_acceptance_set_at_ninety_percent():
    """`python -m eval.intent_harness` with no options is the documented
    command, and every figure quoted against it assumes the 30 + 8 at 90%."""
    args = intent_harness.build_parser().parse_args([])
    assert os.path.samefile(args.graded, GRADED_CSV)
    assert os.path.samefile(args.probes, UNKNOWN_CSV)
    assert args.out is None
    assert args.threshold == intent_harness.PASS_THRESHOLD == 0.90


def test_importing_the_harness_does_not_load_the_env_file():
    """This module imports the harness, and pytest imports every test module
    before running any. An import-time load_dotenv -- which the harness had --
    would hand the whole suite the developer's real key: the leak described in
    tests/test_per_user_source.py. Counting calls, rather than diffing the
    environment, makes this hold on a machine with no backend/.env as well."""
    probe = (
        f"import sys; sys.path.insert(0, {ROOT!r});"
        "import dotenv; calls = [];"
        "dotenv.load_dotenv = lambda *a, **k: calls.append(a) or True;"
        "import eval.intent_harness;"
        "print(len(calls))"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


def _must_not_run():
    raise AssertionError("the harness went past the --out check")


def test_out_never_replaces_a_saved_result(tmp_path, monkeypatch, stub_llm):
    """Refused before the settings file or the model is touched, so a reused
    name costs nothing and a saved measurement survives (FIXES.md item 7)."""
    saved = tmp_path / "saved.csv"
    saved.write_text("set,transcript\ngraded,keep me\n", encoding="utf-8")
    monkeypatch.setattr(intent_harness, "load_settings_file", _must_not_run)

    assert intent_harness.main(["--out", str(saved)]) == 2
    assert saved.read_text(encoding="utf-8") == "set,transcript\ngraded,keep me\n"
    assert stub_llm.call_count == 0


def test_graded_and_probes_options_choose_what_is_measured(tmp_path, monkeypatch, stub_llm):
    """Plumbing only: which files are read, what --out records, and that the
    90% gate applies to a set other than the default. The stub's answers are
    chosen here, so nothing in this test says anything about accuracy."""
    graded = tmp_path / "graded.csv"
    graded.write_text(
        "transcript,expected_intent\nread me the one from sarah,read\nreply to sarah,draft\n",
        encoding="utf-8",
    )
    probes = tmp_path / "probes.csv"
    probes.write_text("transcript,expected_intent\ndelete everything,unknown\n", encoding="utf-8")
    out = tmp_path / "results.csv"

    # The settings file is the developer's; this test supplies its own.
    monkeypatch.setattr(intent_harness, "load_settings_file", lambda: None)
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-used-in-production")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    stub_llm.queue(
        _intent_response(intent="read"),
        _intent_response(intent="unknown", reference="", confidence=0.4),
        _intent_response(intent="unknown", reference="", confidence=0.1),
    )

    code = intent_harness.main(
        ["--graded", str(graded), "--probes", str(probes), "--out", str(out)]
    )

    assert code == 1, "1 of 2 graded is below the 90% gate and must fail"
    assert stub_llm.call_count == 3
    with open(out, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames) == intent_harness.RESULT_FIELDS
        rows = list(reader)
    assert [(r["set"], r["transcript"], r["expected"], r["actual"]) for r in rows] == [
        ("graded", "read me the one from sarah", "read", "read"),
        ("graded", "reply to sarah", "draft", "unknown"),
        ("probe", "delete everything", "unknown", "unknown"),
    ]
    assert [r["source"] for r in rows] == ["graded.csv", "graded.csv", "probes.csv"]
    assert {r["prompt_sha256"] for r in rows} == {intent_harness.prompt_fingerprint()}
    assert all(r["model"] for r in rows)


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


@pytest.mark.skipif(not _LIVE_EVAL, reason=_SKIP_REASON)
def test_heldout_transcripts_dispatch_at_or_above_ninety_percent():
    """The gate that is not marking its own homework.

    INTENT_SYSTEM was rewritten after reading which of the 30 above it missed,
    so a pass there is partly the fix being checked against the transcripts
    that shaped it. These were written and frozen before the rewrite, and
    their results were not used to adjust it. Same model call, same 90%.
    """
    from backend.config import Config

    live_config = Config(require_llm=True)
    rows = _rows(HELDOUT_CSV)
    correct = sum(
        1 for row in rows
        if classify_intent(row["transcript"], live_config)["intent"] == row["expected_intent"]
    )
    rate = correct / len(rows)
    assert rate >= 0.90, f"{correct}/{len(rows)} = {rate:.1%}, below the 90% criterion"


# --- Mis-heard names (recognition accuracy) --------------------------------

def _inbox_candidates():
    return [
        {"id": "e1", "sender_name": "Sarah Chen", "subject": "Dinner this weekend?"},
        {"id": "e2", "sender_name": "David Robinson", "subject": "Project deadline moved to Friday"},
        {"id": "e3", "sender_name": "Dr Amelia Ford", "subject": "Feedback on your research proposal"},
        {"id": "e4", "sender_name": "GitHub", "subject": "Security alert on ds-25"},
    ]


def test_a_mis_heard_name_still_resolves():
    """Recognition routinely returns "sara" for "Sarah". An exact-only match
    would make the feature look broken for clearly spoken commands."""
    from backend.orchestrator.intent import resolve_target
    assert resolve_target(None, "summarise the email from sara", _inbox_candidates()) == "e1"


def test_a_surname_only_reference_resolves():
    from backend.orchestrator.intent import resolve_target
    assert resolve_target(None, "read the one from robinson", _inbox_candidates()) == "e2"


def test_an_unrelated_name_does_not_fuzzy_match():
    """"tara" scores 0.67 against "sarah" and must not be accepted: dispatching
    to the wrong email is worse than asking."""
    from backend.orchestrator.intent import resolve_target
    assert resolve_target(None, "summarise the email from tara", _inbox_candidates()) is None


def test_a_short_name_is_not_fuzzy_matched():
    """Short tokens are one edit from unrelated words, so they need exact hits."""
    from backend.orchestrator.intent import resolve_target
    assert resolve_target(None, "summarise the email from bob", _inbox_candidates()) is None


def test_alternatives_rescue_a_bad_primary_transcript():
    """The recogniser's top guess often drops the name while a lower-ranked
    alternative catches it. Pooling them is still the user's own speech."""
    from backend.orchestrator.intent import resolve_target
    target = resolve_target(
        None,
        "summarise the email from tara",
        _inbox_candidates(),
        alternatives=["summarise the email from sarah"],
    )
    assert target == "e1"


def test_an_exact_match_outranks_a_fuzzy_one():
    """A near miss must never beat a clean hit on a different email."""
    from backend.orchestrator.intent import resolve_target
    candidates = [
        {"id": "fuzzy", "sender_name": "Sarah Chen", "subject": "Lunch"},
        {"id": "exact", "sender_name": "Sara Nguyen", "subject": "Timetable"},
    ]
    assert resolve_target(None, "the email from sara", candidates) == "exact"
