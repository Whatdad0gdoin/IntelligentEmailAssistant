"""Build and apply human review files for the Enron candidate pool.

486 candidates from personal_candidates_bodies.csv were read with their bodies
and given a proposed category, recorded in eval/data/proposed_labels.json:

    Personal 174   Work 146   Promotions 146   Studies 6   unusable 14

That file holds every call, not just the ones that made it into a review file,
so a reviewer can audit the *rejections* as well as the selections -- a
Personal row wrongly filed as Work never reaches the review file, and that is
precisely the error a spot-check of the output cannot find.

--category selects which class to review. Personal and Promotions are the two
that matter here: Personal because Enron's folder heuristic could not supply
it, Promotions because the current class is synthetic and this pool holds real
2001-02 marketing and spam that can replace it.

As in review_labels.py, these proposals come from a language model, so they are
written out as `model_proposed` and only a human pass promotes them to `human`.
See that file for why that distinction is not a formality.

TWO CORRECTIONS APPLIED TO THE POOL

1. Campaign duplicates. One advocacy form letter ("Demand Ken Lay Donate
   Proceeds...") occupied 143 of the first 500 candidates, each copy from a
   different sender. The extractor's content hash missed them because every
   body opens with the sender's own name and postal address. Fixing the dedupe
   to skip the opening words cut it to 11. It is one artefact, not 143 data
   points, and it had been consuming 29% of the pool.

2. Conversation clustering. The pool's Personal rows bunch into a few long
   threads -- one friendship group, one church roster, one family. Twenty rows
   from a single correspondent would let a classifier learn that person's
   writing style rather than the category, so MAX_PER_SENDER caps how many rows
   any one address contributes.

3. Periodicals. The sender cap cannot see a daily newsletter arriving from
   several addresses, so MAX_PER_SUBJECT_FAMILY caps repeats of a subject
   prefix as well. Eleven issues of one gas-price bulletin were crowding the
   Promotions class before this was added.

The Personal review file holds 143 rows for a target of 120, so verification
can reject some without ending below target. Promotions has NO such margin: it
lands on exactly 120, and if rows are rejected the shortfall has to be made up
by relaxing a cap here or by keeping some synthetic HuggingFace rows.

    python -m eval.label_candidates --build --category Personal
    python -m eval.label_candidates --apply --category Personal
"""

import argparse
import csv
import json
import os
import sys

from eval.build_dataset import DATA, FIELDS, ROOT, _write

BODIES = os.path.join(DATA, "personal_candidates_bodies.csv")
ENRON_PATH = os.path.join(DATA, "real_enron.csv")

# Diversity guard, see note 2 above. Higher for Promotions: a spam run comes
# from throwaway addresses, and the forwarded marketing in this corpus all
# carries one forwarder in the From line while the actual advertisers below it
# are all different companies. Capping those at 4 would throw away genuinely
# distinct mail on the strength of an envelope artefact.
MAX_PER_SENDER = {"Personal": 4, "Promotions": 8, "Work": 4, "Studies": 4}
DEFAULT_CAP = 4

# A second diversity guard, on the subject line. The sender cap alone cannot
# see a daily newsletter: eleven issues of "Enerfax Gas, Oil, Liquids..."
# arrive from several different addresses, are genuinely different messages by
# content hash, and are still one publication. Capping repeats of a subject
# prefix keeps a periodical from crowding out the rest of the class.
# Per category: a marketing class legitimately contains several rounds of the
# same campaign -- that is what promotional mail is -- whereas repeated subject
# lines in Personal are one conversation thread, which is not three data points.
MAX_PER_SUBJECT_FAMILY = {"Personal": 2, "Promotions": 3, "Work": 2, "Studies": 2}
DEFAULT_FAMILY_CAP = 2
SUBJECT_FAMILY_CHARS = 30


def review_path(category):
    return os.path.join(DATA, f"review_{category.lower()}.csv")

REVIEW_FIELDS = [
    "row", "verified", "proposed_category", "confidence", "rationale",
    "sender", "subject", "body_preview", "id",
]

# Proposed labels live in eval/data/proposed_labels.json, keyed by message id.
#
# They were keyed by row number until the candidate pool was re-extracted to fix
# the dedupe bug described above. Re-extraction renumbers every row, which
# silently repoints a row-keyed label at a different email -- so the labels are
# keyed on the message id, which is derived from the message path and does not
# move. Anything keyed by position in a regenerated file is a latent mislabel.

LABELS_PATH = os.path.join(DATA, "proposed_labels.json")

UNUSABLE = "UNUSABLE"   # header dump, bounce, or empty forward: excluded, not guessed at


def _labels():
    if not os.path.exists(LABELS_PATH):
        sys.exit(f"Missing {LABELS_PATH}.")
    with open(LABELS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _candidates(source="candidates"):
    """Rows available for review.

    "candidates" is the mined pool from extract_personal_candidates.
    "enron" is the Work class already sitting in real_enron.csv, which needs
    reviewing for the opposite reason: those rows are labelled folder_heuristic
    ("it was in the inbox"), and reading them showed roughly a fifth are not
    Work at all -- spam, club flyers and fantasy football among them. Same
    failure the Personal folder had.
    """
    if source == "enron":
        if not os.path.exists(ENRON_PATH):
            sys.exit(f"Missing {ENRON_PATH}.")
        with open(ENRON_PATH, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["label_source"] == "folder_heuristic"]
        return {i: r for i, r in enumerate(rows, 1)}
    if not os.path.exists(BODIES):
        sys.exit(f"Missing {BODIES}. Run: python -m eval.extract_personal_candidates")
    with open(BODIES, encoding="utf-8") as f:
        return {int(r["row"]): r for r in csv.DictReader(f)}


def build(category, source="candidates"):
    rows = _candidates(source)
    labels = _labels()
    cap = MAX_PER_SENDER.get(category, DEFAULT_CAP)
    family_cap = MAX_PER_SUBJECT_FAMILY.get(category, DEFAULT_FAMILY_CAP)
    selected, per_sender, dropped_cap = [], {}, 0
    per_family, dropped_family = {}, 0

    for row in sorted(rows):
        candidate = rows[row]
        label = labels.get(candidate["id"])
        if label is None:
            continue
        label_category, confidence, rationale = label
        # The enron source is a re-review of rows already in the dataset, so
        # every one is included whatever it is now proposed to be -- the whole
        # point is to check the corrections. The diversity caps are for
        # sampling a large pool and would silently drop rows here.
        if source != "enron":
            if label_category != category:
                continue
            sender = candidate["sender"].split("<")[-1].strip("<> ").lower()
            if per_sender.get(sender, 0) >= cap:
                dropped_cap += 1
                continue
            family = " ".join(candidate["subject"].lower().split())[:SUBJECT_FAMILY_CHARS]
            if per_family.get(family, 0) >= family_cap:
                dropped_family += 1
                continue
        else:
            sender = candidate["sender"]
            family = candidate["subject"]
        per_sender[sender] = per_sender.get(sender, 0) + 1
        per_family[family] = per_family.get(family, 0) + 1
        selected.append({
            "row": row,
            "verified": "",
            "proposed_category": label_category,
            "confidence": confidence,
            "rationale": rationale,
            "sender": candidate["sender"],
            "subject": candidate["subject"],
            "body_preview": " ".join(candidate["body"].split())[:300],
            "id": candidate["id"],
        })

    path = review_path(category)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(selected)

    weak = sum(1 for s in selected if s["confidence"] == "weak")
    tally = {}
    for cat, _, _ in labels.values():
        tally[cat] = tally.get(cat, 0) + 1
    unusable = tally.pop(UNUSABLE, 0)

    print(f"  read and labelled {sum(tally.values())} candidates: {tally}")
    print(f"  {unusable} excluded as unusable (header dumps, bounces, empty forwards)")
    print(f"  {dropped_cap} dropped by the per-sender cap of {cap}, "
          f"{dropped_family} by the subject-family cap of {family_cap}")
    print(f"  wrote {len(selected)} {category} rows -> {os.path.relpath(path, ROOT)}")
    print(f"  {weak} marked weak -- read those first")
    print(f"  distinct senders: {len(per_sender)}")
    print("")
    print("  Fill in `verified` for every row (y | Work | Personal | Promotions | Studies | skip)")
    print(f"  Then: python -m eval.label_candidates --apply --category {category}")


VALID = {"Work", "Personal", "Promotions", "Studies"}


def apply(category, source="candidates"):
    path = review_path(category)
    if not os.path.exists(path):
        sys.exit(f"{path} does not exist. Run --build first.")
    with open(path, encoding="utf-8") as f:
        review = list(csv.DictReader(f))

    unverified = [r["row"] for r in review if not (r["verified"] or "").strip()]
    if unverified:
        sys.exit(
            f"{len(unverified)} of {len(review)} rows are still unverified "
            f"(first: row {unverified[0]}).\n"
            "Every row needs a person to confirm or correct it before these "
            "labels can be called human. Nothing was written."
        )

    # Keyed on id, not row: the review file and the candidate pool are separate
    # artefacts, and a re-extraction between building and applying would shift
    # every row number while ids stay put.
    rows = {r["id"]: r for r in _candidates(source).values()}
    decisions = {}
    for entry in review:
        verdict = entry["verified"].strip()
        if verdict.lower() == "skip":
            continue
        category = entry["proposed_category"] if verdict.lower() == "y" else verdict
        if category not in VALID:
            sys.exit(f"Row {entry['row']}: '{verdict}' is not y, skip, or a category.")
        if entry["id"] not in rows:
            sys.exit(
                f"Row {entry['row']} (id {entry['id']}) is not in the current "
                f"candidate pool. Rebuild the review file before applying."
            )
        decisions[entry["id"]] = category

    with open(ENRON_PATH, encoding="utf-8") as f:
        existing = list(csv.DictReader(f))
    have = {r["id"] for r in existing}

    # A row already in the file is being RE-labelled, not added: the Work
    # review corrects labels that are already there. Updating in place keeps
    # the row (and its body) and promotes label_source to human.
    updated = 0
    by_id = {r["id"]: r for r in existing}
    for row_id, category in list(decisions.items()):
        if row_id in by_id:
            by_id[row_id]["category"] = category
            by_id[row_id]["label_source"] = "human"
            by_id[row_id]["label_confidence"] = "strong"
            updated += 1
            decisions.pop(row_id)
    if updated:
        print(f"  re-labelled {updated} rows already in the file")

    added = []
    for row_id, category in decisions.items():
        candidate = rows[row_id]
        if candidate["id"] in have:
            continue
        added.append({
            "id": candidate["id"],
            "provenance": "enron",
            "text_origin": "real",
            "label_source": "human",
            "label_confidence": "strong",
            "category": category,
            "subject": candidate["subject"],
            "body": candidate["body"],
            "sender": candidate["sender"],
            "received_at": "",
            "source_ref": candidate["source_ref"],
        })

    combined = existing + added
    _write(ENRON_PATH, [{k: r.get(k, "") for k in FIELDS} for r in combined])
    tally = {}
    for row in added:
        tally[row["category"]] = tally.get(row["category"], 0) + 1
    print(f"  added {len(added)} human-verified rows: {tally}")
    print(f"  real_enron.csv now holds {len(combined)} rows")
    print("  Now re-merge:  python -m eval.build_dataset --merge")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--category", default="Personal",
                        choices=["Personal", "Promotions", "Work", "Studies"])
    parser.add_argument("--source", default="candidates",
                        choices=["candidates", "enron"],
                        help="'enron' reviews the folder-heuristic rows already "
                             "in real_enron.csv")
    args = parser.parse_args()
    if args.build:
        build(args.category, args.source)
    elif args.apply:
        apply(args.category, args.source)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
