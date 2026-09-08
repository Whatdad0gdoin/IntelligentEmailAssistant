"""Groundedness rate for summaries and drafts (FR-01, FR-03; spec section 4.6).

This is the metric the report needs, and it is not accuracy. A summary has no
single correct answer to be measured against, so there is nothing to be accurate
about. What can be measured is whether the system stated anything the source did
not support: every number, amount, date, time and proper noun in the output is
checked against the preprocessed email, and an output with zero unsupported
claims is grounded.

    groundedness rate = outputs with zero ungrounded flags / total outputs

WHY NOT ROUGE

ROUGE scores n-gram overlap against a reference summary. It cannot detect
hallucination -- a fluent, wholly fabricated summary that reuses the email's
vocabulary scores well, and that is precisely the failure this project is meant
to catch. The spec allows ROUGE only alongside groundedness and explicitly
caveated.

In this dataset it cannot be computed at all: DR-01 contains labelled
categories, not reference summaries. Producing ROUGE would mean first writing
reference summaries for every email by hand. If the RTM promises ROUGE, that is
the work it implies, and the number would still not answer the hallucination
question.

WHAT A FLAG DOES AND DOES NOT MEAN

A flag says a token in the output is not in the source. That is evidence of a
problem, not proof of one: a legitimate paraphrase ("next Friday" for a date
written out in full) can flag. Conversely, zero flags does not mean the summary
is true -- only that nothing checkable is missing. Both directions belong in
the report's limitations.

    python -m eval.evaluate_grounding --task summarise --limit 60
    python -m eval.evaluate_grounding --task draft --limit 40
    python -m eval.evaluate_grounding --task both --limit 40 --out grounding.csv
"""

import argparse
import collections
import csv
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", ".env"))

from backend.adapters.headers import SourceEmail  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.orchestrator import grounding  # noqa: E402
from backend.orchestrator.draft import draft_reply  # noqa: E402
from backend.orchestrator.grounding import groundedness_rate  # noqa: E402
from backend.orchestrator.summarise import summarise_email  # noqa: E402
from eval.build_dataset import DATA, ROOT  # noqa: E402

DATASET = os.path.join(DATA, "dataset.csv")


def _as_source_email(row):
    """Adapt a dataset row to the SourceEmail the orchestrator expects.

    The dataset stores what the adapter would have parsed from headers, so no
    model is involved in building this -- the same rule as everywhere else.
    """
    return SourceEmail(
        id=row["id"],
        thread_id=row["id"],
        sender=row.get("sender", ""),
        sender_name=(row.get("sender", "").split("<")[0].strip().strip('"')
                     or row.get("sender", "").split("@")[0]),
        recipient="",
        subject=row.get("subject", ""),
        received_at=row.get("received_at", ""),
        unread=False,
        body_text=row.get("body", ""),
    )


def _load(path, limit):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        # Balanced across categories so the rate is not dominated by one class.
        by_category = collections.defaultdict(list)
        for row in rows:
            by_category[row["category"]].append(row)
        per_class = max(1, limit // max(1, len(by_category)))
        rows = [r for c in sorted(by_category) for r in by_category[c][:per_class]]
    return rows


def _run(task, rows, config):
    """Returns (outputs, errors). Errors are production failures, not flags."""
    outputs, errors = [], []
    for index, row in enumerate(rows, 1):
        email = _as_source_email(row)
        try:
            if task == "summarise":
                result = summarise_email(email, config, use_cache=False)
            else:
                result = draft_reply(
                    email,
                    "Acknowledge the email and say a reply will follow.",
                    config,
                    user_email="student@monash.edu",
                )
            result["_row"] = row
            outputs.append(result)
        except Exception as exc:
            # A summary that could not be produced is not an ungrounded summary.
            # Folding these into the rate would let a run that mostly failed
            # report a high groundedness score on the handful that survived.
            errors.append({"id": row["id"], "category": row["category"],
                           "error": type(exc).__name__, "detail": str(exc)[:120]})
        if index % 10 == 0 or index == len(rows):
            print(f"  {index}/{len(rows)}", flush=True)
    return outputs, errors


def _output_text(output):
    """The generated text that was checked, for either task."""
    if "draft" in output:
        return output["draft"]
    return " ".join(output.get("summary", [])
                    + [item["text"] for item in output.get("action_items", [])])


def _report(task, outputs, errors, elapsed):
    print("\n" + "=" * 72)
    print(f"{task.upper()}  (FR-01)" if task == "summarise" else f"{task.upper()}  (FR-03)")

    attempted = len(outputs) + len(errors)
    stats = groundedness_rate(outputs)
    print(f"\n  attempted        {attempted}")
    print(f"  produced         {len(outputs)}")
    print(f"  failed outright  {len(errors)}"
          f"{'  <-- not counted in the rate below' if errors else ''}")
    print(f"\n  GROUNDEDNESS RATE  {stats['rate']:.1%}  "
          f"({stats['grounded']} clean / {stats['total']} produced)")
    print(f"  flagged outputs    {stats['flagged']}")
    print(f"  entity backend     {stats['entity_backend']}"
          f"{'   (spaCy NER)' if stats['entity_backend'] == 'spacy' else ''}")
    print(f"  {elapsed:.1f}s for {attempted} emails ({elapsed / max(1, attempted):.2f}s each)")

    # How much was actually checked. A groundedness rate computed over outputs
    # containing no numbers, dates or names is not evidence of anything -- it
    # is a rate over an empty check, and it would sit at 100% no matter how
    # badly the model behaved. This is the number that says whether the rate
    # above means something.
    checked, checkable_outputs = 0, 0
    for output in outputs:
        text = _output_text(output)
        count = (len(grounding.extract_typed_claims(text))
                 + len(grounding.extract_proper_nouns(text)))
        checked += count
        if count:
            checkable_outputs += 1
    produced = len(outputs) or 1
    print(f"\n  claims checked     {checked} across {len(outputs)} outputs "
          f"({checked / produced:.1f} per output)")
    print(f"  outputs with at least one checkable claim: "
          f"{checkable_outputs}/{len(outputs)}"
          f"{'   <-- rate is vacuous below this' if checkable_outputs < produced // 2 else ''}")

    reasons = collections.Counter()
    claims = collections.Counter()
    for output in outputs:
        for flag in output.get("ungrounded_flags", []):
            reasons[flag["reason"]] += 1
            claims[flag["claim"][:40]] += 1
    if reasons:
        print("\n  Flags by kind")
        for reason, count in reasons.most_common():
            print(f"    {count:>4}  {reason}")
        print("\n  Most frequently flagged claims")
        for claim, count in claims.most_common(8):
            print(f"    {count:>4}  {claim!r}")

    groups = collections.defaultdict(list)
    for output in outputs:
        row = output["_row"]
        groups[(row["text_origin"], row["category"])].append(output)
    print(f"\n  {'text_origin':13}{'category':12}{'n':>5}{'grounded':>11}")
    for key in sorted(groups):
        sub = groundedness_rate(groups[key])
        print(f"  {key[0]:13}{key[1]:12}{sub['total']:>5}{sub['rate']:>10.1%}")

    if errors:
        kinds = collections.Counter(e["error"] for e in errors)
        print(f"\n  Production failures (reported separately, never as 'grounded')")
        for kind, count in kinds.most_common():
            print(f"    {count:>4}  {kind}")
        print(f"    example: {errors[0]['detail']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=["summarise", "draft", "both"], default="summarise")
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--limit", type=int, default=60,
                        help="emails to score; one model call each, so this is the cost")
    parser.add_argument("--out", default=None, help="write per-output flags to a CSV")
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        sys.exit(f"Missing {args.dataset}. Run: python -m eval.build_dataset --merge")

    try:
        config = Config(require_llm=True, require_auth=False)
    except Exception as exc:
        sys.exit(f"{exc}\n\nThis evaluation calls the real model. Set OPENAI_API_KEY "
                 f"in backend/.env and run it again.")

    # Force the entity extractor to load now, so the backend is reported before
    # any numbers are printed. Which extractor ran changes the result, and a
    # groundedness figure without it is not reproducible.
    grounding._load_spacy()
    if grounding.ENTITY_BACKEND != "spacy":
        print("  NOTE: spaCy is unavailable; the weaker capitalisation heuristic "
              "will be used for proper nouns.\n")

    rows = _load(args.dataset, args.limit)
    tasks = ["summarise", "draft"] if args.task == "both" else [args.task]
    print(f"Scoring {len(rows)} emails x {len(tasks)} task(s) = "
          f"{len(rows) * len(tasks)} model calls.")

    all_rows = []
    for task in tasks:
        started = time.perf_counter()
        outputs, errors = _run(task, rows, config)
        _report(task, outputs, errors, time.perf_counter() - started)
        for output in outputs:
            row = output["_row"]
            all_rows.append({
                "task": task, "id": row["id"], "category": row["category"],
                "text_origin": row["text_origin"],
                "grounded": output["grounded"],
                "flag_count": len(output["ungrounded_flags"]),
                "flags": "; ".join(f"{f['claim']} ({f['reason']})"
                                   for f in output["ungrounded_flags"])[:300],
                "subject": row["subject"][:100],
            })

    print("\nReport the groundedness rate with the entity backend and the sample")
    print("size. If ROUGE is also reported, it must be caveated: it cannot")
    print("detect hallucination, which is the failure this metric exists for.")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nPer-output flags -> {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
