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
"""

import argparse
import collections
import csv
import hashlib
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
from backend.orchestrator.classify import classify_emails
from backend.orchestrator.schemas import CATEGORIES, REVIEW_CATEGORY
from eval.build_dataset import DATA, ROOT

DATASET = os.path.join(DATA, "dataset.csv")
CLASSES = list(CATEGORIES)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all",
                        help="dev to tune against, test for the reported number")
    parser.add_argument("--limit", type=int, default=None,
                        help="score a balanced subset, for a cheap smoke run")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="emails per model call")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to pause between batches; a stronger model "
                             "usually has a lower rate limit than the mini tier")
    parser.add_argument("--out", default=None, help="write per-row predictions to a CSV")
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        sys.exit(f"Missing {args.dataset}. Run: python -m eval.build_dataset --merge")

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
    batches = (len(rows) + args.batch_size - 1) // args.batch_size
    print(f"Scoring {len(rows)} emails ({args.split} split) in {batches} "
          f"batches of {args.batch_size}.")
    if batches > config.max_requests_per_session:
        print(f"  WARNING: {batches} calls exceeds MAX_REQUESTS_PER_SESSION "
              f"({config.max_requests_per_session}); the run will stop early.")

    predictions = {}
    started = time.perf_counter()
    for index in range(0, len(rows), args.batch_size):
        batch = rows[index:index + args.batch_size]
        # use_cache=False: a cached label from an earlier run would make this
        # measure the cache, not the classifier.
        results = classify_emails(
            [{"id": r["id"], "subject": r["subject"], "body": r["body"],
              "sender": r.get("sender", "")} for r in batch],
            config,
            session_key=None,
            user=None,
            use_cache=False,
        )
        for result in results:
            predictions[result["id"]] = result
        print(f"  {min(index + args.batch_size, len(rows))}/{len(rows)}", flush=True)
        if args.delay and index + args.batch_size < len(rows):
            time.sleep(args.delay)

    elapsed = time.perf_counter() - started

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
    _print_metrics("OVERALL", overall)
    print(f"  {elapsed:.1f}s for {len(rows)} emails ({elapsed / max(1, len(rows)):.2f}s each)")

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
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "provenance", "text_origin", "label_source",
                "expected", "predicted", "correct", "confidence", "subject"])
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
                })
        print(f"\nPer-row predictions -> {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
