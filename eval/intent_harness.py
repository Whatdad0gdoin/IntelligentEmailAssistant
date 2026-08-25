"""Voice intent harness (FR-05 acceptance criterion, spec section 6.3).

The criterion is 30 spoken commands across the three intents with at least 90%
dispatched to the correct action. Re-recording audio for every run is not
reproducible and not something a marker can repeat, so the commands live as
written transcripts in eval/data/voice_intents.csv and this script runs the
real classifier over them.

What this does and does not measure: it measures intent classification, which
is where the errors are. It does not measure the browser's speech recognition
accuracy -- that is Chrome's Web Speech API, not our code, and the transcripts
here are written to include the artefacts it actually produces (no
punctuation, lowercase, filler words).

    python -m eval.intent_harness

Needs a real OPENAI_API_KEY: it calls the model, once per transcript. Exits
non-zero below the threshold so it can gate CI.
"""

import argparse
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "backend", ".env"))

from backend.config import Config  # noqa: E402
from backend.orchestrator.intent import classify_intent  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GRADED = os.path.join(DATA_DIR, "voice_intents.csv")
UNKNOWN_PROBES = os.path.join(DATA_DIR, "voice_intents_unknown.csv")

PASS_THRESHOLD = 0.90


def load(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("transcript")]


def run(rows, config, label):
    """Classify every row. Returns (correct, total, mistakes)."""
    correct = 0
    mistakes = []
    confusion = Counter()

    print(f"\n{label} ({len(rows)} transcripts)")
    print("-" * 78)
    for row in rows:
        transcript = row["transcript"]
        expected = row["expected_intent"]
        result = classify_intent(transcript, config)
        actual = result["intent"]
        confusion[(expected, actual)] += 1

        if actual == expected:
            correct += 1
            mark = "ok  "
        else:
            mistakes.append((transcript, expected, actual, result["confidence"]))
            mark = "MISS"
        print(f"  {mark}  {actual:10} (conf {result['confidence']:.2f})  {transcript}")

    return correct, len(rows), mistakes, confusion


def report(correct, total, mistakes, confusion, threshold):
    rate = correct / total if total else 0.0
    print("-" * 78)
    print(f"  correct: {correct}/{total} = {rate:.1%}  (threshold {threshold:.0%})")

    if mistakes:
        print("\n  misclassified:")
        for transcript, expected, actual, confidence in mistakes:
            print(f"    expected {expected:10} got {actual:10} (conf {confidence:.2f})  {transcript}")

    print("\n  confusion (expected -> actual):")
    for (expected, actual), count in sorted(confusion.items()):
        flag = "" if expected == actual else "   <-- error"
        print(f"    {expected:10} -> {actual:10} {count:3}{flag}")
    return rate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=PASS_THRESHOLD)
    parser.add_argument("--skip-unknown-probes", action="store_true")
    args = parser.parse_args()

    try:
        config = Config(require_llm=True)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    correct, total, mistakes, confusion = run(
        load(GRADED), config, "FR-05 acceptance set: summarise / read / draft"
    )
    rate = report(correct, total, mistakes, confusion, args.threshold)

    if not args.skip_unknown_probes:
        # Not part of the graded 30. This checks the other half of the
        # requirement -- that out-of-scope commands come back as `unknown`
        # rather than being forced into one of the three actions.
        u_correct, u_total, u_mistakes, u_confusion = run(
            load(UNKNOWN_PROBES), config, "Out-of-scope probes: must return unknown"
        )
        report(u_correct, u_total, u_mistakes, u_confusion, 0.0)

    passed = rate >= args.threshold
    print(f"\n{'PASS' if passed else 'FAIL'}: {rate:.1%} on the {total}-transcript acceptance set\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
