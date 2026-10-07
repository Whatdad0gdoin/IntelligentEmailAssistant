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

    python -m eval.intent_harness                  # the graded run, ~38 calls
    python -m eval.intent_harness --baseline-only  # dataset difficulty, 0 calls

    # the held-out sets (82 calls), keeping every per-transcript answer
    python -m eval.intent_harness --graded eval/data/voice_intents_heldout.csv \
        --probes eval/data/voice_intents_heldout_unknown.csv --out results.csv

With no options it measures exactly the 30 + 8 it always has, so the
documented command still produces the number quoted against it. --graded and
--probes exist because the 30 are no longer a clean test of a prompt fixed
after reading their failures (FIXES.md item 5): a held-out set has to be
measured by the same code, or the two numbers are not comparable.

`unknown` is scored differently in the two sets, deliberately. On the graded 30
every command *is* one of the three actions, so an `unknown` there is a miss
against the criterion -- the criterion says "dispatched to the correct action",
and declining to dispatch is not dispatching. On the out-of-scope probes
`unknown` is the only correct answer. Both sets report wrong dispatches apart
from declines, because those cost the user completely different things.

Needs a real OPENAI_API_KEY: it calls the model, once per transcript. Exits
non-zero below the threshold so it can gate CI.
"""

import argparse
import csv
import hashlib
import math
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

from backend.config import Config  # noqa: E402
from backend.orchestrator import prompts  # noqa: E402
from backend.orchestrator.intent import UNKNOWN, classify_intent  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GRADED = os.path.join(DATA_DIR, "voice_intents.csv")
UNKNOWN_PROBES = os.path.join(DATA_DIR, "voice_intents_unknown.csv")
ENV_FILE = os.path.join(ROOT, "backend", ".env")

PASS_THRESHOLD = 0.90

# One row per transcript in an --out file. The first five match what
# eval/compare_models.py writes for its intent runs, so the two kinds of saved
# result can be read by the same code.
RESULT_FIELDS = (
    "set", "transcript", "expected", "actual", "confidence",
    "source", "model", "prompt_sha256",
)


def load_settings_file():
    """Read backend/.env into the environment -- from main(), never at import.

    It used to run at module scope. That was harmless while only the command
    line imported this module, but the test suite now imports it to check the
    CLI defaults, and pytest imports every test module before running any. An
    import-time load would hand the whole session the developer's real key --
    the leak backend/mailserver.py had, which tests/test_per_user_source.py
    now guards against.
    """
    load_dotenv(ENV_FILE)


def prompt_fingerprint():
    """First 12 hex digits of sha256(INTENT_SYSTEM).

    Every figure this harness prints depends on the prompt as much as on the
    model, and a saved result that does not say which prompt produced it is
    how FR-02 ended up with a headline nobody can tie to a file (FIXES.md
    item 7). Twelve digits is plenty to tell two prompts apart and short
    enough to quote.
    """
    return hashlib.sha256(prompts.INTENT_SYSTEM.encode("utf-8")).hexdigest()[:12]


def load(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("transcript")]


def run(rows, config, label):
    """Classify every row.

    Returns (correct, total, mistakes, confusion, results), where `results`
    holds one (transcript, expected, actual, confidence) per row, in input
    order, for --out.
    """
    correct = 0
    mistakes = []
    results = []
    confusion = Counter()

    print(f"\n{label} ({len(rows)} transcripts)")
    print("-" * 78)
    for row in rows:
        transcript = row["transcript"]
        expected = row["expected_intent"]
        result = classify_intent(transcript, config)
        actual = result["intent"]
        confusion[(expected, actual)] += 1
        results.append((transcript, expected, actual, result["confidence"]))

        if actual == expected:
            correct += 1
            mark = "ok  "
        else:
            mistakes.append((transcript, expected, actual, result["confidence"]))
            mark = "MISS"
        print(f"  {mark}  {actual:10} (conf {result['confidence']:.2f})  {transcript}")

    return correct, len(rows), mistakes, confusion, results


def result_rows(set_name, source, results, model, fingerprint):
    """Shape run() output for write_results(): one dict per transcript."""
    return [
        {
            "set": set_name,
            "transcript": transcript,
            "expected": expected,
            "actual": actual,
            "confidence": confidence,
            "source": os.path.basename(source),
            "model": model,
            "prompt_sha256": fingerprint,
        }
        for transcript, expected, actual, confidence in results
    ]


def out_path_problem(path):
    """Why `path` cannot take an --out file, or None if it can.

    Checked before the first API call, so a bad path costs nothing. An existing
    file is refused rather than replaced: the per-row predictions behind the
    FR-02 headline were lost by being overwritten (FIXES.md item 7), and a
    measurement worth saving is worth a new name.
    """
    if os.path.exists(path):
        return f"{path} already exists; results are never overwritten, choose a new name"
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        return f"directory {parent} does not exist"
    return None


def write_results(path, rows):
    """Write per-transcript results. Mode "x" refuses to replace a file that
    appeared after out_path_problem() looked."""
    with open(path, "x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def wilson(correct, total, z=1.96):
    """95% confidence interval for a proportion, Wilson score.

    Reported because at n=30 a single transcript moves the headline by 3.3
    points, so a bare percentage implies far more precision than 30 samples
    can carry. Wilson rather than the normal approximation: the latter
    misbehaves near 1.0, which is where these rates sit.
    """
    if not total:
        return 0.0, 0.0
    p = correct / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = (z / denominator) * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, centre - spread), min(1.0, centre + spread)


def taxonomy(confusion):
    """Split errors by what they cost the user.

    A wrong dispatch and an `unknown` are both misses against the acceptance
    criterion, but they are not the same failure. A wrong dispatch summarises
    the wrong email or drafts a reply the user never asked for. An `unknown`
    shows the transcript back and asks -- mildly annoying, never destructive,
    and per spec 6.3 the designed response to doubt. Pooling them hides the
    only distinction a user would actually notice.
    """
    wrong = declined = 0
    for (expected, actual), count in confusion.items():
        if expected == actual:
            continue
        if actual == UNKNOWN:
            declined += count
        else:
            wrong += count
    return wrong, declined


def per_intent(confusion):
    """Precision, recall and F1 per intent, derived from the confusion counts."""
    labels = sorted({label for pair in confusion for label in pair})
    stats = {}
    for label in labels:
        tp = confusion.get((label, label), 0)
        support = sum(c for (e, _), c in confusion.items() if e == label)
        predicted = sum(c for (_, a), c in confusion.items() if a == label)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        stats[label] = (support, predicted, precision, recall, f1)
    return stats


def report(correct, total, mistakes, confusion, threshold):
    rate = correct / total if total else 0.0
    low, high = wilson(correct, total)
    wrong, declined = taxonomy(confusion)

    print("-" * 78)
    if not total:
        print("  no transcripts loaded -- nothing measured")
        return 0.0

    print(f"  correct: {correct}/{total} = {rate:.1%}  (threshold {threshold:.0%})")
    print(f"  95% CI (Wilson): [{low:.1%}, {high:.1%}]   one transcript = {1 / total:.1%}")

    print("\n  errors by cost to the user:")
    print(f"    wrong dispatch (acted on the wrong intent) {wrong:3}/{total} = {wrong / total:.1%}")
    print(f"    declined to guess (returned unknown)       {declined:3}/{total} = {declined / total:.1%}")

    stats = per_intent(confusion)
    print("\n  per intent (support = true label, predicted = times chosen):")
    print(f"    {'intent':10} {'support':>7} {'pred':>5} {'precision':>10} {'recall':>7} {'F1':>6}")
    graded_f1 = []
    for label, (support, predicted, precision, recall, f1) in stats.items():
        # Recall and F1 are undefined for a label nothing in this set is
        # labelled as -- printing 0.000 there would read as a failure when it
        # only means the label was never a correct answer here. Precision still
        # means something: it counts predictions that were all necessarily wrong.
        recall_cell = f"{recall:6.1%}" if support else "     -"
        f1_cell = f"{f1:6.3f}" if support else "     -"
        print(f"    {label:10} {support:7} {predicted:5} {precision:9.1%} {recall_cell} {f1_cell}")
        if support:
            graded_f1.append(f1)
    if graded_f1:
        print(f"    macro-F1 over the {len(graded_f1)} intents present: {sum(graded_f1) / len(graded_f1):.3f}")

    if mistakes:
        print("\n  misclassified:")
        for transcript, expected, actual, confidence in mistakes:
            print(f"    expected {expected:10} got {actual:10} (conf {confidence:.2f})  {transcript}")

    print("\n  confusion (expected -> actual):")
    for (expected, actual), count in sorted(confusion.items()):
        flag = "" if expected == actual else "   <-- error"
        print(f"    {expected:10} -> {actual:10} {count:3}{flag}")
    return rate


# Keyword cues per intent, for the dataset-difficulty probe below. These were
# written AFTER reading the 30 transcripts, so the probe is not a fair rival
# classifier -- it is an upper bound on how far this particular set can be
# solved by spotting a verb. That is the point: if a regex tuned to the answers
# scores near the model, the set is measuring vocabulary, not understanding.
# They predate voice_intents_heldout*.csv and were not changed for it, so on
# that set the same probe is an untuned keyword rival rather than a bound.
_CUES = (
    ("read", r"read|aloud|out loud"),
    ("summarise", r"summar|\bsum up\b|gist|brief|condens"),
    ("draft", r"draft|repl|respon|compos|answer|writ|prepar"),
)


def keyword_baseline(transcript):
    """First cue wins, in the order above. No model, no API call."""
    for intent, pattern in _CUES:
        if re.search(pattern, transcript):
            return intent
    return UNKNOWN


def difficulty_probe(graded=GRADED, probes=UNKNOWN_PROBES):
    """How much of a graded set is solvable by keyword alone.

    Runs offline so a marker can check this claim without a key or any spend.
    """
    print("\nDataset-difficulty probe: keyword baseline, no model (0 API calls)")
    print(f"  graded: {os.path.basename(graded)}   probes: {os.path.basename(probes)}")
    print("-" * 78)
    for path, label in ((graded, "graded set"), (probes, "out-of-scope probes")):
        rows = load(path)
        if not rows:
            print(f"  {label:22} no transcripts in {path}")
            continue
        hits = wrong = 0
        misses = []
        for row in rows:
            guess = keyword_baseline(row["transcript"])
            if guess == row["expected_intent"]:
                hits += 1
            else:
                misses.append((row["expected_intent"], guess, row["transcript"]))
                if guess != UNKNOWN:
                    wrong += 1
        print(f"  {label:22} {hits}/{len(rows)} = {hits / len(rows):5.1%}"
              f"   of which wrong dispatches: {wrong}")
        for expected, guess, transcript in misses:
            print(f"      expected {expected:10} got {guess:10}  {transcript}")

    # Which rows carry one unambiguous cue for their own intent, and which
    # carry none or two. The model's errors concentrate entirely in the latter.
    rows = load(graded)
    if not rows:
        return
    ambiguous = []
    for row in rows:
        cues = {intent for intent, pattern in _CUES if re.search(pattern, row["transcript"])}
        if cues != {row["expected_intent"]}:
            ambiguous.append((row["expected_intent"], sorted(cues) or ["none"], row["transcript"]))
    print(f"\n  rows with exactly one cue, matching their own label: "
          f"{len(rows) - len(ambiguous)}/{len(rows)}")
    print(f"  rows that are cue-free or carry competing cues:      {len(ambiguous)}/{len(rows)}")
    for expected, cues, transcript in ambiguous:
        print(f"      {expected:10} cues={','.join(cues):20} {transcript}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=PASS_THRESHOLD)
    parser.add_argument("--skip-unknown-probes", action="store_true")
    parser.add_argument(
        "--baseline-only", action="store_true",
        help="run only the offline keyword baseline; makes no API calls and needs no key",
    )
    parser.add_argument(
        "--graded", default=GRADED, metavar="CSV",
        help="graded transcripts, scored against the threshold "
             "(default: the 30-transcript acceptance set)",
    )
    parser.add_argument(
        "--probes", default=UNKNOWN_PROBES, metavar="CSV",
        help="out-of-scope probes, where unknown is the only correct answer "
             "(default: the 8 original probes)",
    )
    parser.add_argument(
        "--out", metavar="CSV",
        help="also write one row per transcript here; refuses to replace an existing file",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.baseline_only:
        difficulty_probe(args.graded, args.probes)
        return 0

    if args.out:
        problem = out_path_problem(args.out)
        if problem:
            print(f"--out: {problem}", file=sys.stderr)
            return 2

    load_settings_file()
    try:
        config = Config(require_llm=True)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    fingerprint = prompt_fingerprint()
    graded_name = os.path.basename(args.graded)
    print(f"model {config.openai_model}, temperature {config.openai_temperature}, "
          f"INTENT_SYSTEM sha256 {fingerprint}")

    correct, total, mistakes, confusion, results = run(
        load(args.graded), config, f"Graded set {graded_name}: summarise / read / draft"
    )
    rate = report(correct, total, mistakes, confusion, args.threshold)
    saved = result_rows("graded", args.graded, results, config.openai_model, fingerprint)

    if not args.skip_unknown_probes:
        # Not part of the graded set. This checks the other half of the
        # requirement -- that out-of-scope commands come back as `unknown`
        # rather than being forced into one of the three actions.
        u_correct, u_total, u_mistakes, u_confusion, u_results = run(
            load(args.probes), config,
            f"Out-of-scope probes {os.path.basename(args.probes)}: must return unknown",
        )
        report(u_correct, u_total, u_mistakes, u_confusion, 0.0)
        saved += result_rows("probe", args.probes, u_results, config.openai_model, fingerprint)

    if args.out:
        write_results(args.out, saved)
        print(f"\nper-transcript results: {args.out} ({len(saved)} rows)")

    difficulty_probe(args.graded, args.probes)

    passed = rate >= args.threshold
    print(f"\n{'PASS' if passed else 'FAIL'}: {rate:.1%} on the {total}-transcript "
          f"graded set ({graded_name})\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
