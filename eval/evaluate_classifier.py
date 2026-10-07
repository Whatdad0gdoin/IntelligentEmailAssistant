"""Categorisation accuracy (FR-02, DR-02).

Runs the real classifier -- the same backend.orchestrator.classify path
/api/inbox uses, with the same schema, evidence verification and confidence
threshold -- over eval/data/dataset.csv and scores it against the labels.

WHY THE HEADLINE NUMBER IS REPORTED THREE WAYS

Review is an abstention, not an answer. The classifier routes an email there
when the evidence span it quoted is not in the source, or when its confidence
is below the threshold (spec 4.3). That is the system working, so scoring it as
a miss understates the classifier -- and scoring it as a hit would let a model
reach 100% by abstaining on everything. So this reports:

    coverage   share of rows given a real category rather than Review
    accuracy   over covered rows only -- how good the answers are when it answers
    strict     Review counted as wrong -- the pessimistic bound

Quote all three or none of them. A coverage figure without an accuracy figure
hides abstention; an accuracy figure without coverage hides how often it
declined to try.

WHY IT IS ALSO BROKEN DOWN BY PROVENANCE

Class and source are still correlated in this dataset: Studies is the generated
class, the other three are Enron. A single pooled number therefore partly
measures "can the model tell real mail from model-written mail", which is not
FR-02. The per-provenance and per-text_origin tables are the honest reading,
and eval/data/README.md says the same thing.

    python -m eval.evaluate_classifier                 # full run, needs a key
    python -m eval.evaluate_classifier --limit 40      # cheap smoke run
    python -m eval.evaluate_classifier --out preds.csv # save per-row predictions

TWO DIFFERENT BATCH SIZES

--batch-size is how many rows this script hands to classify_emails per loop.
It is not how many emails go into one model call: classify_emails decides that
itself, from CLASSIFY_BATCH_SIZE (emails per call, default 1) and
CLASSIFY_CONCURRENCY (calls in flight at once, default 25) -- the same settings
/api/inbox runs with, so this measures what the inbox does. With the default
--batch-size 20, a loop is 20 single-email calls, all in flight at once; with
CLASSIFY_BATCH_SIZE=20 it is one 20-email call, which is how runs 1-10 in
eval/BENCHMARKS.md were made:

    CLASSIFY_BATCH_SIZE=20 python -m eval.evaluate_classifier --split test

Both settings are printed at the start and written into every row of --out,
so a predictions file says which configuration produced it.

A FAILED CALL IS NOT AN ABSTENTION

classify_emails routes the emails of a failed call (a rate limit that outlasted
the client's retry, say) to Review, which is right for the inbox and wrong for
a measurement: scored as Review, an outage reads as caution. Those rows are
re-sent up to REATTEMPTS times; each row's re-attempts and its Review reason
are written to --out, and any row still unanswered is reported loudly.
"""

import argparse
import collections
import csv
import hashlib
import math
import os
import sys
import time

from dotenv import load_dotenv

# Must precede the Config import: Config reads the environment at construction,
# and backend/.env is where the key actually lives (same order as backend/run.py
# and eval/intent_harness.py).
load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", ".env"))

from backend.config import Config  # noqa: E402
from backend.orchestrator.classify import (  # noqa: E402
    REASON_CALL_FAILED,
    REASON_NOT_SENT,
    classify_emails,
)
from backend.orchestrator.client import LLMUnavailable  # noqa: E402
from backend.orchestrator.schemas import CATEGORIES, REVIEW_CATEGORY  # noqa: E402
from eval.build_dataset import DATA, ROOT  # noqa: E402

DATASET = os.path.join(DATA, "dataset.csv")
CLASSES = list(CATEGORIES)

# For measurement completeness only; every re-attempt is recorded per row.
REATTEMPTS = 3
REATTEMPT_WAIT_SECONDS = 20
# Review reasons that mean "never answered", not "declined to answer".
_UNANSWERED = {REASON_CALL_FAILED, REASON_NOT_SENT}


DEV_FRACTION = 40   # percent of rows reserved for tuning


def _split_of(row_id):
    """Deterministic dev/test assignment from the row id.

    Hashed rather than stored so the split is reproducible from the CSV alone
    and cannot drift as rows are added. Tuning happens on dev; the number that
    goes in the report is measured once on test. A prompt tuned against the
    same rows it is scored on has been fitted to the test set, and that figure
    describes nothing but the tuning.
    """
    digest = hashlib.sha1(row_id.encode("utf-8")).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < DEV_FRACTION else "test"


def _load(path, limit=None, split="all"):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if split != "all":
        rows = [r for r in rows if _split_of(r["id"]) == split]
    if limit:
        # Take a balanced slice so a smoke run is not all one class.
        per_class = max(1, limit // len(CLASSES))
        by_category = collections.defaultdict(list)
        for row in rows:
            by_category[row["category"]].append(row)
        rows = [r for c in sorted(by_category) for r in by_category[c][:per_class]]
    return rows


def _score(pairs):
    """pairs: [(expected, predicted)]. Returns a metrics dict."""
    total = len(pairs)
    if not total:
        return None
    reviewed = sum(1 for _, p in pairs if p == REVIEW_CATEGORY)
    covered = [(e, p) for e, p in pairs if p != REVIEW_CATEGORY]
    correct = sum(1 for e, p in covered if e == p)

    per_class = {}
    for label in CLASSES:
        tp = sum(1 for e, p in covered if e == label and p == label)
        fp = sum(1 for e, p in covered if e != label and p == label)
        fn = sum(1 for e, p in pairs if e == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "support": sum(1 for e, _ in pairs if e == label),
            "precision": precision, "recall": recall, "f1": f1,
        }

    # Averaged over classes actually present in this slice, not all four. The
    # per-provenance tables contain single-class groups -- "generated" is only
    # Studies -- and dividing by four there reported macro-F1 0.250 for a group
    # the classifier got 100% right, which reads as a failure and is not one.
    present = [v["f1"] for v in per_class.values() if v["support"]]
    macro_f1 = sum(present) / len(present) if present else 0.0
    return {
        "n": total,
        "reviewed": reviewed,
        "coverage": (total - reviewed) / total,
        "accuracy": correct / len(covered) if covered else 0.0,
        "strict": correct / total,
        "macro_f1": macro_f1,
        "per_class": per_class,
    }


def _print_metrics(title, metrics):
    if not metrics:
        return
    print(f"\n{title}")
    print(f"  n={metrics['n']}  coverage={metrics['coverage']:.1%}  "
          f"accuracy(covered)={metrics['accuracy']:.1%}  "
          f"strict={metrics['strict']:.1%}  macro-F1={metrics['macro_f1']:.3f}")


def _print_breakdown(title, pairs_by_key):
    print(f"\n{title}")
    print(f"  {'group':22}{'n':>5}{'coverage':>11}{'accuracy':>11}{'strict':>9}{'macroF1':>9}")
    for key in sorted(pairs_by_key):
        m = _score(pairs_by_key[key])
        if m:
            print(f"  {key:22}{m['n']:>5}{m['coverage']:>10.1%}{m['accuracy']:>11.1%}"
                  f"{m['strict']:>9.1%}{m['macro_f1']:>9.3f}")


def _print_confusion(pairs):
    labels = CLASSES + [REVIEW_CATEGORY]
    matrix = collections.Counter(pairs)
    width = max(len(l) for l in labels) + 2
    print("\nConfusion matrix (rows = true label, columns = predicted)")
    print(" " * width + "".join(f"{l[:10]:>12}" for l in labels))
    for true in CLASSES:
        cells = "".join(f"{matrix.get((true, p), 0):>12}" for p in labels)
        print(f"  {true:<{width - 2}}{cells}")


def _classify_loop(rows, config):
    """Classify one loop's rows, re-sending any whose call failed.

    Returns ({id: result}, {id: Review reason}, {id: re-attempts}).
    """
    results, reasons = {}, {}
    reattempts = {row["id"]: 0 for row in rows}
    todo = list(rows)
    for attempt in range(1 + REATTEMPTS):
        if attempt:
            print(f"    {len(todo)} row(s) unanswered; re-attempt {attempt}/{REATTEMPTS} "
                  f"in {REATTEMPT_WAIT_SECONDS}s", flush=True)
            time.sleep(REATTEMPT_WAIT_SECONDS)
            for row in todo:
                reattempts[row["id"]] += 1
        found = {}
        try:
            # use_cache=False: a cached label from an earlier run would make
            # this measure the cache, not the classifier. session_key=None: the
            # per-session cap guards a login, and this is not one.
            answered = classify_emails(
                [{"id": r["id"], "subject": r["subject"], "body": r["body"],
                  "sender": r.get("sender", "")} for r in todo],
                config,
                session_key=None,
                user=None,
                use_cache=False,
                review_reasons=found,
            )
        except LLMUnavailable:
            # Every call in the loop failed: classify_emails reports an outage
            # rather than an all-Review answer, so nothing came back to keep.
            for row in todo:
                reasons[row["id"]] = REASON_CALL_FAILED
            continue
        for result in answered:
            results[result["id"]] = result
            reasons.pop(result["id"], None)
        reasons.update(found)
        todo = [r for r in todo if found.get(r["id"]) in _UNANSWERED]
        if not todo:
            break
    return results, reasons, reattempts


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all",
                        help="dev to tune against, test for the reported number")
    parser.add_argument("--limit", type=int, default=None,
                        help="score a balanced subset, for a cheap smoke run")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="rows handed to classify_emails per loop. Emails per "
                             "MODEL CALL is CLASSIFY_BATCH_SIZE; see the docstring")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to pause between loops; a stronger model "
                             "usually has a lower rate limit than the mini tier")
    parser.add_argument("--out", default=None, help="write per-row predictions to a CSV")
    parser.add_argument("--force", action="store_true",
                        help="allow --out to replace an existing file")
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        sys.exit(f"Missing {args.dataset}. Run: python -m eval.build_dataset --merge")
    if args.out and os.path.exists(args.out) and not args.force:
        # Checked before any model call. Run 9's predictions were lost when
        # run 10 reused its path (eval/BENCHMARKS.md).
        sys.exit(f"Refusing to overwrite {args.out}: it may be the only record of an "
                 f"earlier run. Choose a new --out, or pass --force.")

    try:
        config = Config(require_llm=True, require_auth=False)
    except Exception as exc:
        # Not a soft failure: without a key this measures nothing, and a run
        # that quietly scored a stub would be worse than no run at all.
        sys.exit(
            f"{exc}\n\n"
            "This evaluation calls the real model. Set OPENAI_API_KEY in "
            "backend/.env and run it again."
        )

    rows = _load(args.dataset, args.limit, args.split)
    loops = math.ceil(len(rows) / args.batch_size)
    calls = sum(math.ceil(len(rows[i:i + args.batch_size]) / config.classify_batch_size)
                for i in range(0, len(rows), args.batch_size))
    # The run's configuration, written into every output row as well: a file
    # that cannot say what produced it is how dev_preds.csv became unusable.
    settings = {
        "model": config.openai_model,
        "classify_batch_size": config.classify_batch_size,
        "classify_concurrency": config.classify_concurrency,
        "loop_size": args.batch_size,
    }
    print(f"Scoring {len(rows)} emails ({args.split} split) with {config.openai_model}.")
    print(f"  {loops} loops of up to {args.batch_size} rows (--batch-size); "
          f"CLASSIFY_BATCH_SIZE={config.classify_batch_size} emails per model call, "
          f"CLASSIFY_CONCURRENCY={config.classify_concurrency} calls at once: "
          f"{calls} model calls.")

    predictions, reasons, reattempts = {}, {}, {}
    started = time.perf_counter()
    for index in range(0, len(rows), args.batch_size):
        batch = rows[index:index + args.batch_size]
        results, loop_reasons, loop_reattempts = _classify_loop(batch, config)
        predictions.update(results)
        reasons.update(loop_reasons)
        reattempts.update(loop_reattempts)
        print(f"  {min(index + args.batch_size, len(rows))}/{len(rows)}", flush=True)
        if args.delay and index + args.batch_size < len(rows):
            time.sleep(args.delay)

    elapsed = time.perf_counter() - started
    unanswered = sorted(i for i, reason in reasons.items() if reason in _UNANSWERED)

    pairs, by_provenance, by_origin, by_source = [], {}, {}, {}
    for row in rows:
        predicted = predictions.get(row["id"], {}).get("category", REVIEW_CATEGORY)
        pair = (row["category"], predicted)
        pairs.append(pair)
        by_provenance.setdefault(row["provenance"], []).append(pair)
        by_origin.setdefault(row["text_origin"], []).append(pair)
        by_source.setdefault(row["label_source"], []).append(pair)

    overall = _score(pairs)
    print("\n" + "=" * 72)
    print("  " + "  ".join(f"{key}={value}" for key, value in settings.items()))
    _print_metrics("OVERALL", overall)
    # Wall time, with up to CLASSIFY_CONCURRENCY calls overlapping: a
    # throughput figure, not a per-email latency.
    print(f"  {elapsed:.1f}s wall time for {len(rows)} emails")

    print("\nWhy rows went to Review")
    for reason, count in collections.Counter(reasons.values()).most_common():
        print(f"  {reason:38}{count:>5}")
    print(f"  rows re-sent after a failed call: {sum(1 for n in reattempts.values() if n)}")
    if unanswered:
        print(f"\n  WARNING: {len(unanswered)} rows were never answered after {REATTEMPTS} "
              f"re-attempts and are scored as Review. This run is incomplete; do not "
              f"quote it as a measurement of the classifier.")

    print("\nPer class (over covered rows)")
    print(f"  {'class':14}{'support':>9}{'precision':>11}{'recall':>9}{'F1':>8}")
    for label, stats in overall["per_class"].items():
        print(f"  {label:14}{stats['support']:>9}{stats['precision']:>11.1%}"
              f"{stats['recall']:>9.1%}{stats['f1']:>8.3f}")

    _print_confusion(pairs)
    _print_breakdown("By provenance (where the TEXT came from)", by_provenance)
    _print_breakdown("By text_origin", by_origin)
    _print_breakdown("By label_source (who decided the label)", by_source)

    print("\nReport these together, never the pooled accuracy alone: class and")
    print("source are correlated in this dataset, so part of any pooled figure")
    print("is the model telling real mail from generated mail, not FR-02.")

    if args.out:
        # The first nine columns are the format runs 1-10 were saved in, so
        # files compare column for column; the rest were added for run 11.
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "provenance", "text_origin", "label_source",
                "expected", "predicted", "correct", "confidence", "subject",
                "review_reason", "reattempts", *settings])
            writer.writeheader()
            for row in rows:
                result = predictions.get(row["id"], {})
                predicted = result.get("category", REVIEW_CATEGORY)
                writer.writerow({
                    "id": row["id"], "provenance": row["provenance"],
                    "text_origin": row["text_origin"], "label_source": row["label_source"],
                    "expected": row["category"], "predicted": predicted,
                    "correct": row["category"] == predicted,
                    "confidence": result.get("confidence", 0.0),
                    "subject": row["subject"][:120],
                    "review_reason": reasons.get(row["id"], ""),
                    "reattempts": reattempts.get(row["id"], 0),
                    **settings,
                })
        print(f"\nPer-row predictions -> {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
