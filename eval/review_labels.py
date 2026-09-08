"""Build and apply the human review file for the Enron Personal slice.

WHY THIS EXISTS AS A SEPARATE STEP

The 120 rows Enron's folder heuristic called Personal were re-read one by one
and given proposed labels (see PROPOSED below). Those proposals came from a
language model, not a person, so they are written out as
`label_source = model_proposed` and they do NOT go into dataset.csv.

That distinction is the whole point. The reason to relabel this slice at all
was to obtain ground truth that is independent of a model. Labels produced by
one model and then used to grade another model are not ground truth -- they
share failure modes, so the emails that confuse the classifier are
disproportionately the ones that confused the labeller, and measured accuracy
comes out higher than the truth. Marking them `human` without a person reading
them would quietly turn a real evaluation into a circular one.

So: propose here, adjudicate in the CSV, promote with `--apply`.

    python -m eval.review_labels --build     # writes review_enron_personal.csv
    ...open it, fill in the `verified` column...
    python -m eval.review_labels --apply     # promotes to label_source=human

`--apply` refuses to run while any row is unverified. Rows are promoted to
`human` only because a person confirmed or corrected each one, which is what
makes the label citable.
"""

import argparse
import csv
import os
import sys

from eval.build_dataset import DATA, FIELDS, ROOT, _write

REVIEW_PATH = os.path.join(DATA, "review_enron_personal.csv")
ENRON_PATH = os.path.join(DATA, "real_enron.csv")

REVIEW_FIELDS = [
    "row",
    "verified",          # y = proposal correct, or type a category to override
    "proposed_category",
    "confidence",
    "rationale",
    "sender",
    "subject",
    "body_preview",
    "id",
]

# Proposed labels, keyed on the row's position in the original Personal slice.
# (category, confidence, rationale)
#
# `weak` marks a genuine judgement call, not a low-effort guess -- those are the
# rows where two annotators could reasonably disagree, and they are the ones
# worth reading first.
PROPOSED = {
    1: ("Work", "strong", "Payroll notice from an employer system"),
    2: ("Work", "weak", "Industry mailing list forwarded for work; newsletter-shaped but job-relevant"),
    3: ("Personal", "strong", "Superbowl party invite, asks to forward to friends"),
    4: ("Work", "strong", "CEO all-staff survey results"),
    5: ("Work", "weak", "Internal product announcement to staff; marketing copy but internal comms"),
    6: ("Personal", "strong", "Thanks for lunch, catching up with a friend"),
    7: ("Work", "strong", "Industry technical assessment circulated internally"),
    8: ("Personal", "strong", "Negotiating a private golf club purchase, I am broke"),
    9: ("Work", "strong", "Stock option grant, employee compensation"),
    10: ("Work", "strong", "Memo on office space policy"),
    11: ("Work", "weak", "Transactional notice for a work market-access credential"),
    12: ("Work", "weak", "Internal product announcement"),
    13: ("Personal", "weak", "Satirical song about the company shared between colleagues; social not task"),
    14: ("Work", "strong", "Internal product management announcement"),
    15: ("Work", "strong", "Organisational announcement"),
    16: ("Work", "strong", "Trading desk enquiry"),
    17: ("Work", "strong", "Internal EHS site launch"),
    18: ("Work", "strong", "Staff promotion list"),
    19: ("Work", "weak", "Work credential expiry notice"),
    20: ("Work", "weak", "Corporate training course; professional development, not university"),
    21: ("Work", "weak", "Internal product announcement"),
    22: ("Work", "strong", "IT policy on email address formats"),
    23: ("Work", "strong", "Job candidate following up after campus recruitment"),
    24: ("Personal", "weak", "Joke forward between colleagues, this is pretty good, its safe"),
    25: ("Work", "strong", "Requested data comparison for a colleague"),
    26: ("Work", "strong", "Office move logistics"),
    27: ("Work", "strong", "Internal group announcement"),
    28: ("Work", "strong", "Organisational announcement on workforce"),
    29: ("Work", "strong", "Trading desk counterparty discussion"),
    30: ("Work", "strong", "Recruiter listing job openings"),
    31: ("Work", "strong", "Org chart distribution"),
    32: ("Work", "weak", "Internal product announcement"),
    33: ("Work", "weak", "HR asking staff to verify home address; employer admin, not personal admin"),
    34: ("Work", "strong", "Trading bid detail"),
    35: ("Work", "strong", "Market forecast circulated internally"),
    36: ("Work", "weak", "Internal product announcement"),
    37: ("Work", "strong", "Colleague apologising for a missed document"),
    38: ("Work", "weak", "Company-wide social event from the chairman; workplace event"),
    39: ("Work", "weak", "Work credential expiry notice"),
    40: ("Work", "strong", "Colleague on an outstanding request"),
    41: ("Work", "strong", "Office phone system change"),
    42: ("Work", "weak", "Work credential expiry notice"),
    43: ("Work", "strong", "Trading desk pricing enquiry"),
    44: ("Work", "strong", "Utility data circulated internally"),
    45: ("Work", "strong", "New business unit announcement"),
    46: ("Work", "strong", "IT systems notice"),
    47: ("Work", "strong", "Market report circulated internally"),
    48: ("Personal", "weak", "Colleague inviting to a charity golf scramble; social invitation"),
    49: ("Work", "strong", "Research request about customer accounts"),
    50: ("Work", "strong", "Regulatory decision circulated internally"),
    51: ("Work", "strong", "Trading bid"),
    52: ("Work", "weak", "Internal product announcement"),
    53: ("Personal", "weak", "Political and religious opinion forward from a private address"),
    54: ("Work", "strong", "Process update to the team"),
    55: ("Work", "strong", "Colleague on contract status"),
    56: ("Promotions", "strong", "Marketing for a paid publication, FREE trial offer"),
    57: ("Personal", "weak", "Bare this is good forward from an external contact; content unknown"),
    58: ("Work", "strong", "Employee parking allocation"),
    59: ("Work", "strong", "Press article circulated internally"),
    60: ("Work", "strong", "Cross-team query on a deal"),
    61: ("Work", "weak", "Industry mailing list news release; newsletter-shaped but job-relevant"),
    62: ("Work", "weak", "Informal subject but the content is a REC trading enquiry from a broker"),
    63: ("Work", "strong", "Account listings for a colleague"),
    64: ("Work", "strong", "Forwarding an account information request"),
    65: ("Personal", "strong", "Relative sold her house, moved in with her daughter, holiday wishes"),
    66: ("Personal", "weak", "Farewell to colleagues with a private email address; relationship not task"),
    67: ("Personal", "strong", "Super Bowl party and fish fry at a private residence"),
    68: ("Promotions", "weak", "Weekly DOE newsletter; subscribed bulk mail"),
    69: ("Work", "weak", "Internal product announcement"),
    70: ("Work", "strong", "Industry bidders conference invitation"),
    71: ("Personal", "strong", "Baby shower invitation with RSVP and gift registry"),
    72: ("Work", "strong", "IT mailbox migration notice"),
    73: ("Work", "weak", "Work credential expiry notice"),
    74: ("Personal", "weak", "Leaving the company, sharing home address and private email"),
    75: ("Personal", "strong", "Saturday cookout to welcome friends to Houston"),
    76: ("Personal", "weak", "Chain forward of a PowerPoint; social not task"),
    77: ("Personal", "strong", "Warm personal note with home address, you are why I have no regrets"),
    78: ("Work", "strong", "Trading strategy question to a colleague"),
    79: ("Work", "strong", "Employee savings plan administration"),
    80: ("Work", "strong", "Product structuring discussion"),
    81: ("Work", "strong", "Cost centre and employee ID admin"),
    82: ("Work", "strong", "Deal costs discussion"),
    83: ("Work", "strong", "Performance bond payment details"),
    84: ("Personal", "weak", "Novelty desktop flag chain forward"),
    85: ("Personal", "strong", "Sharing personal contact details to stay in touch"),
    86: ("Personal", "strong", "Home address and personal phone numbers to a friend"),
    87: ("Work", "strong", "Equity research circulated internally"),
    88: ("Work", "strong", "Quarterly earnings announcement to staff"),
    89: ("Studies", "weak", "GMAT preparation course; exam prep for graduate admission, hosted at work"),
    90: ("Work", "weak", "Business contact announcing a new address; professional not personal"),
    91: ("Personal", "strong", "Asking colleagues for personal contact details to stay in touch"),
    92: ("Work", "strong", "Floor plan circulated internally"),
    93: ("Work", "strong", "Office phone system change"),
    94: ("Work", "strong", "Reorganisation announcement"),
    95: ("Work", "strong", "Trading desk counterparty periods"),
    96: ("Work", "strong", "Pricing rationale to a colleague"),
    97: ("Work", "strong", "Stock delisting announcement to staff"),
    98: ("Work", "strong", "Payroll systems change"),
    99: ("Work", "strong", "Trading desk holding position"),
    100: ("Personal", "weak", "Colleague laid off, personal check-in mixed with one work handover item"),
    101: ("Work", "strong", "Savings plan data error notice"),
    102: ("Work", "strong", "Enrolment dealsheet for a colleague"),
    103: ("Work", "strong", "Monthly reporting instructions"),
    104: ("Work", "strong", "Customer account number request"),
    105: ("Work", "strong", "Role and responsibility announcement"),
    106: ("Work", "weak", "Job opportunity networking, opens with a personal are you OK"),
    107: ("Work", "strong", "Customer list cross-check"),
    108: ("Work", "weak", "Transactional notice for a work credential"),
    109: ("Work", "strong", "Executive recruiter sending a position description"),
    110: ("Work", "strong", "Forwarding an account information request"),
    111: ("Personal", "strong", "Photo from Dad, signed Love Dad"),
    112: ("Personal", "strong", "Wedding photos from a friend"),
    113: ("Personal", "strong", "Household finances with a spouse, phone bill and savings"),
    114: ("Personal", "weak", "Thanks sweets on a travel itinerary forwarded to a spouse"),
    115: ("Personal", "weak", "E-ticket itinerary booked via the corporate agent; could be work travel"),
    116: ("Personal", "strong", "Wedding photos to a spouse, signed Tu Esposa"),
    117: ("Personal", "weak", "Personal photo order shipped; transactional, taxonomy has no Updates class"),
    118: ("Personal", "weak", "Personal photo order confirmation; transactional"),
    119: ("Personal", "strong", "Congratulations on an engagement, informal banter"),
    120: ("Personal", "weak", "Personal photo order shipped; transactional"),
}


def _original_personal_rows():
    """The 120 folder-labelled Personal rows, in their original order.

    Read from git if they are no longer in real_enron.csv -- they were removed
    when Enron was cut to Work only.
    """
    import subprocess

    rows = []
    if os.path.exists(ENRON_PATH):
        with open(ENRON_PATH, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["category"] == "Personal"]
    if not rows:
        blob = subprocess.run(
            ["git", "show", "HEAD:eval/data/real_enron.csv"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        if blob.returncode != 0:
            sys.exit("Could not recover the Personal rows from real_enron.csv or from git.")
        rows = [r for r in csv.DictReader(blob.stdout.splitlines())
                if r["category"] == "Personal"]
    return rows


def build():
    rows = _original_personal_rows()
    if len(rows) != len(PROPOSED):
        sys.exit(
            f"Expected {len(PROPOSED)} rows to match the proposed labels, found "
            f"{len(rows)}. The source slice changed; re-read it before relabelling."
        )

    out = []
    for index, row in enumerate(rows, 1):
        category, confidence, rationale = PROPOSED[index]
        body = " ".join((row["body"] or "").split())[:300]
        out.append({
            "row": index,
            "verified": "",
            "proposed_category": category,
            "confidence": confidence,
            "rationale": rationale,
            "sender": row["sender"],
            "subject": row["subject"],
            "body_preview": body,
            "id": row["id"],
        })

    with open(REVIEW_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(out)

    counts = {}
    weak = 0
    for entry in out:
        counts[entry["proposed_category"]] = counts.get(entry["proposed_category"], 0) + 1
        if entry["confidence"] == "weak":
            weak += 1
    print(f"  wrote {len(out)} rows -> {os.path.relpath(REVIEW_PATH, ROOT)}")
    print(f"  proposed: {counts}")
    print(f"  {weak} marked weak -- read those first, they are the judgement calls")
    print("")
    print("  Fill in the `verified` column for every row:")
    print("    y                 the proposed category is right")
    print("    Work | Personal | Promotions | Studies   to override it")
    print("    skip              drop the row from the dataset entirely")
    print("")
    print("  Then: python -m eval.review_labels --apply")


VALID = {"Work", "Personal", "Promotions", "Studies"}


def apply():
    if not os.path.exists(REVIEW_PATH):
        sys.exit(f"{REVIEW_PATH} does not exist. Run --build first.")

    with open(REVIEW_PATH, encoding="utf-8") as f:
        review = list(csv.DictReader(f))

    unverified = [r["row"] for r in review if not (r["verified"] or "").strip()]
    if unverified:
        # Refusing here is the point of the whole file. Promoting unread rows to
        # label_source=human would be a false claim about how the data was made.
        sys.exit(
            f"{len(unverified)} of {len(review)} rows are still unverified "
            f"(first: row {unverified[0]}).\n"
            "Every row needs a person to confirm or correct it before these "
            "labels can be called human. Nothing was written."
        )

    decisions = {}
    for entry in review:
        verdict = entry["verified"].strip()
        if verdict.lower() == "skip":
            continue
        if verdict.lower() == "y":
            decisions[entry["id"]] = entry["proposed_category"]
        elif verdict in VALID:
            decisions[entry["id"]] = verdict
        else:
            sys.exit(
                f"Row {entry['row']}: '{verdict}' is not y, skip, or one of {sorted(VALID)}."
            )

    source = {r["id"]: r for r in _original_personal_rows()}
    with open(ENRON_PATH, encoding="utf-8") as f:
        existing = list(csv.DictReader(f))
    existing = [r for r in existing if r["id"] not in decisions]

    added = []
    for row_id, category in decisions.items():
        row = dict(source[row_id])
        row["category"] = category
        row["label_source"] = "human"
        row["label_confidence"] = "strong"
        added.append(row)

    combined = existing + added
    _write(ENRON_PATH, [{k: r.get(k, "") for k in FIELDS} for r in combined])

    counts = {}
    for row in added:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    print(f"  promoted {len(added)} reviewed rows to label_source=human: {counts}")
    print(f"  real_enron.csv now holds {len(combined)} rows")
    print("")
    print("  Now re-merge:  python -m eval.build_dataset --merge")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write the review CSV")
    parser.add_argument("--apply", action="store_true", help="promote verified labels")
    args = parser.parse_args()

    if args.build:
        build()
    elif args.apply:
        apply()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
