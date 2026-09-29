"""Keyboard-driven review of a review_<category>.csv file.

    python -m eval.review_cli --category Work

Shows each email in turn with the label its folder gave it and the label a
language model proposed, and records YOUR decision in the `verified` column.
`eval.label_candidates --apply` then promotes those rows to label_source=human.

WHY THIS DOES NOT DECIDE ANYTHING ITSELF
----------------------------------------
The whole value of these labels is that a person chose them. The proposals came
from a language model, and grading a model against another model's labels is
circular: the emails that confuse the classifier are disproportionately the
ones that confused the labeller, so measured accuracy comes out higher than the
truth. This tool therefore only presents and records. It never fills in a row
on its own, and it is not something an agent should run on anyone's behalf.

It exists because the alternative -- editing 120 cells by hand in a CSV with
the body text scrolled off to the right -- is slow enough that people start
typing `y` down the column without reading, which defeats the purpose just as
thoroughly.

ORDER
-----
Rows where the model disagreed with the folder come first, then the ones it
was unsure about, then the rest. The disagreements are where a label actually
changes, so they get your freshest attention.

Progress is saved after every answer, so you can stop with q and pick up where
you left off.
"""

import argparse
import csv
import os
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "eval", "data")
ENRON_PATH = os.path.join(DATA, "real_enron.csv")

CATEGORIES = ["Work", "Personal", "Promotions", "Studies"]
KEYS = {"1": "Work", "2": "Personal", "3": "Promotions", "4": "Studies"}

BODY_CHARS = 1400


def review_path(category):
    return os.path.join(DATA, f"review_{category.lower()}.csv")


def load(path):
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def save(path, fields, rows):
    # Written to a temporary file and renamed into place, so a Ctrl+C in the
    # middle of a write cannot leave half a review file behind.
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, path)


def full_bodies():
    """The review file carries a truncated preview. Judging an email on its
    first 300 characters is how a signature line gets mistaken for the point,
    so show the whole cleaned body when it is available."""
    if not os.path.exists(ENRON_PATH):
        return {}
    with open(ENRON_PATH, encoding="utf-8") as f:
        return {r["id"]: r.get("body", "") for r in csv.DictReader(f)}


def priority(row, category):
    if row["proposed_category"] != category:
        return 0          # the model disagrees with the folder: a label changes
    if row.get("confidence") == "weak":
        return 1          # the model agreed but was unsure
    return 2              # agreement with confidence: quickest to confirm


def show(row, index, total, category, body):
    width = 78
    proposed = row["proposed_category"]
    disagree = proposed != category

    print("\n" + "=" * width)
    print(f"  {index} of {total}    (row {row['row']} in the file)")
    print("=" * width)
    print(f"  From:     {row.get('sender', '')}")
    print(f"  Subject:  {row.get('subject', '')}")
    print("-" * width)
    text = (body or row.get("body_preview", "")).strip()
    if len(text) > BODY_CHARS:
        text = text[:BODY_CHARS].rstrip() + "  [...]"
    for para in text.split("\n"):
        wrapped = textwrap.wrap(para, width - 4) or [""]
        for line in wrapped:
            print(f"  {line}")
    print("-" * width)
    print(f"  Folder said:    {category}")
    marker = "   <-- DISAGREES" if disagree else ""
    print(f"  Model proposes: {proposed}  ({row.get('confidence', '')}){marker}")
    if row.get("rationale"):
        print(f"  Model's reason: {row['rationale']}")
    print("-" * width)


def ask(proposed):
    prompt = (
        f"  [Enter] accept {proposed}   "
        "1 Work  2 Personal  3 Promotions  4 Studies   "
        "x exclude   b back   q save+quit\n  > "
    )
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("", "y"):
            return "y"
        if answer in KEYS:
            return KEYS[answer]
        if answer in ("x", "b", "q"):
            return answer
        print("  Not a choice. Press Enter, 1-4, x, b or q.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", default="Work", choices=CATEGORIES)
    parser.add_argument("--redo", action="store_true",
                        help="Revisit rows already verified, not just blank ones.")
    args = parser.parse_args()

    # Email bodies contain characters a default Windows console cannot encode.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    path = review_path(args.category)
    if not os.path.exists(path):
        sys.exit(f"{path} does not exist. Build it with eval.label_candidates --build first.")

    fields, rows = load(path)
    bodies = full_bodies()

    queue = [r for r in rows if args.redo or not (r.get("verified") or "").strip()]
    queue.sort(key=lambda r: (priority(r, args.category), int(r["row"])))

    done_already = len(rows) - len([r for r in rows if not (r.get("verified") or "").strip()])
    contested = sum(1 for r in queue if priority(r, args.category) == 0)
    print(f"\n  {path}")
    print(f"  {len(rows)} rows, {done_already} already verified, {len(queue)} to go.")
    print(f"  {contested} of those are rows where the model disagrees with the folder.")
    print("  They come first. Read the body before you answer.\n")

    if not queue:
        print("  Nothing left to review.")
    history = []
    i = 0
    while i < len(queue):
        row = queue[i]
        show(row, i + 1, len(queue), args.category, bodies.get(row["id"]))
        answer = ask(row["proposed_category"])

        if answer == "q":
            break
        if answer == "b":
            if history:
                prev = history.pop()
                prev["verified"] = ""
                save(path, fields, rows)
                i -= 1
            else:
                print("  Already at the first row of this session.")
            continue

        row["verified"] = "skip" if answer == "x" else answer
        save(path, fields, rows)
        history.append(row)
        i += 1

    remaining = [r for r in rows if not (r.get("verified") or "").strip()]
    print("\n" + "=" * 78)
    if remaining:
        print(f"  Saved. {len(remaining)} row(s) still to review.")
        print(f"  Resume with:  python -m eval.review_cli --category {args.category}")
    else:
        changes = sum(1 for r in rows
                      if r["verified"] not in ("y", "skip") and r["verified"] != args.category)
        accepted_changes = sum(1 for r in rows
                               if r["verified"] == "y" and r["proposed_category"] != args.category)
        excluded = sum(1 for r in rows if r["verified"] == "skip")
        print(f"  All {len(rows)} rows verified.")
        print(f"    relabelled away from {args.category}: {changes + accepted_changes}")
        print(f"    excluded from the dataset:        {excluded}")
        print("")
        source = " --source enron" if args.category == "Work" else ""
        print("  Apply them with:")
        print(f"    python -m eval.label_candidates --apply --category {args.category}{source}")
        print("  then rebuild the merged set:")
        print("    python -m eval.build_dataset --merge")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
