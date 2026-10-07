"""Build the labelled evaluation dataset (DR-01, DR-02).

    python -m eval.build_dataset --enron
    python -m eval.build_dataset --huggingface     # needs HF_TOKEN
    python -m eval.build_dataset --generate        # costs API budget
    python -m eval.build_dataset --merge

WHY THE DATASET IS SPLIT BY PROVENANCE
--------------------------------------
Three sources with three different label qualities feed one evaluation set, and
an accuracy figure computed across them means nothing unless you can say which
rows produced it. Every row therefore carries:

  provenance       enron | huggingface | generated   -- where the TEXT came from
  label_source     folder_heuristic | dataset_label | generation_prompt | human
  label_confidence weak | strong                     -- how much to trust the label

`provenance` answers "is this a real email or one we made up?", which is the
distinction that matters for the report. `label_source` answers the separate
and equally important question "who decided this label?". A generated email has
a perfect label by construction (we told the model what to write) but is not
real mail; an Enron email is unquestionably real but its label is inferred from
a folder name. Collapsing those two into one column would hide the trade-off.

WHAT THE ENRON CORPUS ACTUALLY GIVES US
---------------------------------------
Scanning the real folder distribution: the corpus is overwhelmingly
`all_documents`, `inbox`, `sent_items`, `discussion_threads` -- organisational
folders, not category labels. It is a corporate mailbox, so nearly everything
in it is Work.

The `personal` / `myfriends` / `family` folders look like a Personal signal and
are not one: reading all 120 rows they produced, about 77 were Work (payslips,
stock options, org announcements), 11 were Promotions (expiry notices, order
confirmations) and only ~27 were genuinely personal. People file their payslips
in a folder called "personal". Those mappings were removed -- see
ENRON_FOLDER_LABELS below.

So Enron supplies Work, and essentially ZERO Personal, Promotions and Studies.
Any claim that it provides all four classes does not survive contact with the
data.
"""

import argparse
import csv
import email
import hashlib
import os
import re
import sys
import tarfile
from email import policy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "eval", "data")
RAW = os.path.join(DATA, "raw")

ENRON_ARCHIVE = os.path.join(RAW, "enron_mail_20150507.tar.gz")

FIELDS = [
    "id",
    "provenance",
    "text_origin",
    "label_source",
    "label_confidence",
    "category",
    "subject",
    "body",
    "sender",
    "received_at",
    "source_ref",
]

# Folders whose name genuinely indicates a category. Everything else in the
# corpus is organisational and gets no label rather than a guessed one.
# WORK ONLY. The Personal mappings that used to sit here -- myfriends,
# personalfolder, personal, friends, family -- were removed after the 120 rows
# they produced were read by hand. Roughly a quarter were genuinely personal
# ("Superbowl Party", "Baby Shower for the Little Transter", "FW: Wedding
# photos"). The rest split two ways:
#
#   ~77 were Work        Your May 31 Pay Advice / 2001 Special Stock Option
#                        Grant Awards / RE: Unforced capacity credits
#   ~11 were Promotions  Your Digital ID is about to expire (x4) /
#                        ImageStation Order (x3) / EREN Network News
#
# A folder called "personal" is where an Enron employee filed their payslips,
# not where personal correspondence lived. The heuristic was therefore ~25%
# accurate on this class and contaminated it with two others, so an accuracy
# figure computed against it would mostly measure filing habits at Enron in
# 2001 -- and would penalise the classifier for correctly calling a payroll
# notice Work.
#
# Enron is a corporate mailbox: it supplies Work reliably and essentially no
# Promotions or Studies. Real personal correspondence is in there, but at a
# density too low for the folder names to find. Recovering it needs hand
# labelling, not a better folder map.
ENRON_FOLDER_LABELS = {
    "inbox": ("Work", "weak"),
    "sent_items": ("Work", "weak"),
    "sent": ("Work", "weak"),
    "_sent_mail": ("Work", "weak"),
    "meetings": ("Work", "weak"),
    "hr": ("Work", "weak"),
}

QUOTE_MARKERS = re.compile(
    r"^\s*(-{2,}\s*Original Message|-{5,}|>|On .{0,80} wrote:|From:\s)", re.MULTILINE
)


def _clean(text, limit=4000):
    """Strip quoted history and collapse whitespace. Not the production
    preprocessor -- this is dataset hygiene, kept separate on purpose so the
    evaluation set does not silently depend on the code under test."""
    if not text:
        return ""
    match = QUOTE_MARKERS.search(text)
    if match and match.start() > 120:
        text = text[: match.start()]
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def _row_id(provenance, source_ref):
    digest = hashlib.sha1(f"{provenance}:{source_ref}".encode("utf-8")).hexdigest()[:12]
    return f"{provenance}-{digest}"


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows)} rows -> {os.path.relpath(path, ROOT)}")


# --------------------------------------------------------------------- enron


def build_enron(per_category=120, scan_limit=250_000):
    if not os.path.exists(ENRON_ARCHIVE):
        sys.exit(
            f"Missing {ENRON_ARCHIVE}.\n"
            "Download it first:\n"
            "  curl -L -o eval/data/raw/enron_mail_20150507.tar.gz \\\n"
            "    https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz"
        )

    counts = {"Work": 0}
    rows = []
    scanned = 0
    # The archive is ordered by mailbox, so taking the first 120 matches drew
    # all of them from one person's inbox -- one job, one set of colleagues,
    # one writing style. A classifier scored on that is partly being asked
    # "does this look like blair-l's mail", which is not the question. Capping
    # per mailbox forces the class to span the corpus instead.
    per_mailbox = {}
    max_per_mailbox = max(1, per_category // 12)

    with tarfile.open(ENRON_ARCHIVE, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            scanned += 1
            if scanned > scan_limit:
                break
            if all(c >= per_category for c in counts.values()):
                break

            parts = member.name.split("/")
            if len(parts) < 4 or parts[0] != "maildir":
                continue
            mailbox = parts[1].lower()
            folder = parts[2].lower()
            label = ENRON_FOLDER_LABELS.get(folder)
            if label is None:
                continue
            category, confidence = label
            if counts.get(category, 0) >= per_category:
                continue
            if per_mailbox.get(mailbox, 0) >= max_per_mailbox:
                continue

            handle = tar.extractfile(member)
            if handle is None:
                continue
            try:
                message = email.message_from_binary_file(handle, policy=policy.default)
            except Exception:
                continue

            body = message.get_body(preferencelist=("plain",))
            body_text = _clean(body.get_content() if body else "")
            subject = (message.get("Subject") or "").strip()

            # Too short to classify or summarise meaningfully.
            if len(body_text) < 120 or not subject:
                continue

            rows.append({
                "id": _row_id("enron", member.name),
                "provenance": "enron",
                "text_origin": "real",
                "label_source": "folder_heuristic",
                "label_confidence": confidence,
                "category": category,
                "subject": subject[:300],
                "body": body_text,
                "sender": (message.get("From") or "").strip()[:200],
                "received_at": (message.get("Date") or "").strip()[:100],
                "source_ref": member.name,
            })
            counts[category] = counts.get(category, 0) + 1
            per_mailbox[mailbox] = per_mailbox.get(mailbox, 0) + 1

    # Human-labelled rows are the expensive part of this dataset and they are
    # not reproducible from the archive: someone read each one. An earlier
    # version of this function wrote the file outright and silently destroyed
    # 263 of them on a rebuild, which is only recoverable because the review
    # files still existed. They are carried across instead.
    existing_path = os.path.join(DATA, "real_enron.csv")
    existing = []
    if os.path.exists(existing_path):
        with open(existing_path, encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    rows, gave_way = keep_human_rows(rows, existing)
    kept = sum(1 for r in rows if r.get("label_source") == "human")
    if kept:
        print(f"  kept all {kept} human-labelled rows already in the file; "
              f"{gave_way} freshly sampled row(s) were the same messages and gave way to them")

    print(f"  scanned {scanned} archive entries")
    print(f"  collected {counts} across {len(per_mailbox)} mailboxes "
          f"(max {max_per_mailbox} each)")
    _write(os.path.join(DATA, "real_enron.csv"), rows)
    return rows


# --------------------------------------------------------------- huggingface


def keep_human_rows(fresh_rows, existing_rows):
    """Merge a fresh archive sample with the rows already on disk.

    Returns (rows, gave_way). Every human-labelled existing row survives with
    its human label. A freshly sampled row with the same id is the same
    message, and it gives way: the sampler walks the archive in a fixed order,
    so a rebuild re-collects exactly the emails people have already read and
    relabelled. Letting the fresh copy win -- as this code once did -- swapped
    120 verified Work rows back to the folder guess and quietly reverted 26
    human relabels while reporting that it had "preserved" the rest.
    """
    human = [r for r in existing_rows if r.get("label_source") == "human"]
    human_ids = {r["id"] for r in human}
    fresh = [r for r in fresh_rows if r["id"] not in human_ids]
    return fresh + human, len(fresh_rows) - len(fresh)


def build_huggingface(source=None, per_category=120):
    """Map the HuggingFace corpus onto this project's four categories.

    TWO FINDINGS DRIVE WHAT THIS DOES.

    1. The corpus is SYNTHETIC, not real mail. 15% of rows contain the
       placeholder `example.com`; bodies carry `bit.ly/fakeprize` and a literal
       `phishing-site`; 13,477 rows share only 2,910 distinct subjects; the
       median body is 87 characters; and one template emits "48hrshrs". It is
       templated text, so `text_origin` is `synthetic` -- which matters, because
       the Week 11 deck cites this source under "Real emails. Not AI testing AI."

    2. Its taxonomy is six classes that are not ours: forum, promotions,
       social_media, spam, updates, verify_code. Only `promotions` maps cleanly
       onto Work/Personal/Promotions/Studies.

    So only `promotions` is imported. Forcing the other five into our four would
    manufacture labels the source never asserted -- `spam` is not `Promotions`,
    and `updates`/`verify_code` are transactional mail that could sit in either
    Work or Personal depending on context. An invented mapping would show up as
    classifier error that is really annotator error.

    The value here is real regardless: Enron supplies no Promotions at all, and
    this fills that class with 2,245 consistently labelled examples.
    """
    source = source or os.path.join(RAW, "hf_full_dataset.csv")
    if not os.path.exists(source):
        sys.exit(
            "Missing " + source + "." + '\\n' +
            "The dataset is gated on HuggingFace; sign in, accept the terms at" + '\\n' +
            "  https://huggingface.co/datasets/jason23322/high-accuracy-email-classifier" + '\\n' +
            "and download full_dataset.csv into eval/data/raw/."
        )

    KEEP = {"promotions": "Promotions"}
    rows = []
    skipped = {}
    kept_counts = {}

    with open(source, encoding="utf-8", errors="replace") as f:
        for record in csv.DictReader(f):
            source_category = (record.get("category") or "").strip().lower()
            category = KEEP.get(source_category)
            if category is None:
                skipped[source_category] = skipped.get(source_category, 0) + 1
                continue
            # Cap per class: the source has 2,245 promotions against Enron's 120
            # Work, and an unbalanced set makes accuracy a measure of the class
            # prior rather than the classifier.
            if kept_counts.get(category, 0) >= per_category:
                continue
            body = _clean(record.get("body") or "")
            subject = (record.get("subject") or "").strip()
            if not body or not subject:
                continue
            rows.append({
                "id": _row_id("huggingface", record.get("id") or f"{subject}:{body[:40]}"),
                "provenance": "huggingface",
                "text_origin": "synthetic",
                "label_source": "dataset_label",
                "label_confidence": "strong",
                "category": category,
                "subject": subject[:300],
                "body": body,
                "sender": "",
                "received_at": "",
                "source_ref": record.get("id") or "",
            })
            kept_counts[category] = kept_counts.get(category, 0) + 1

    print(f"  kept {len(rows)} rows from category 'promotions' (capped at {per_category})")
    print(f"  skipped (taxonomy does not map): {skipped}")
    _write(os.path.join(DATA, "real_huggingface.csv"), rows)
    return rows


# ----------------------------------------------------------------- generated


# Scenario axes. The generator draws one value from each so no two prompts are
# alike. This is a direct response to what the HuggingFace corpus got wrong:
# 13,477 rows sharing 2,910 subjects is a templating artefact, and a synthetic
# set that repeats itself measures memorisation rather than classification.
STUDIES_SCENARIOS = [
    "assignment deadline change", "exam timetable release", "tutorial room change",
    "lecture recording unavailable", "group project coordination", "thesis supervision meeting",
    "unit enrolment problem", "library loan recall", "scholarship application outcome",
    "academic integrity module reminder", "placement application update", "lab safety induction",
    "special consideration outcome", "course plan advice", "graduation application",
    "research ethics approval", "conference travel funding", "student society AGM",
    "fee due date reminder", "WAM and results release", "textbook list for next semester",
    "practical class swap request", "supervisor feedback on a draft", "unit guide correction",
]

STUDIES_SENDERS = [
    ("Unit Coordinator", "a.chen@monash.edu"), ("Faculty Admin", "science.admin@monash.edu"),
    ("Thesis Supervisor", "r.patel@monash.edu"), ("Student Services", "no-reply@monash.edu"),
    ("Tutor", "j.nguyen@monash.edu"), ("Library Services", "library@monash.edu"),
    ("Examinations Office", "exams@monash.edu"), ("Group Member", "k.silva@student.monash.edu"),
]

STUDIES_TONES = [
    "brief and administrative", "warm and encouraging", "formal and procedural",
    "urgent, with a deadline in the next few days", "apologetic about a change",
    "detailed, listing several numbered points",
]

GENERATED_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "body"],
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
}

GENERATE_SYSTEM = (
    "You write realistic university email for a labelled research dataset. "
    "Produce ONE plausible email body and subject. Write only the message itself: "
    "no preamble, no commentary, no markdown. Vary sentence length and structure. "
    "Include concrete specifics (dates, unit codes, room numbers, names) so the text "
    "resembles genuine correspondence. Never reuse a phrase you would obviously reuse."
)


def build_generated(per_category, categories):
    """Generate the Studies class (DR-01).

    WHY ONLY STUDIES. The Week 11 dataset slide is the strategy this follows:
    real corpora supply the other classes, and generation "fills a gap, not the
    test". Enron contains no academic mail and the HuggingFace taxonomy has no
    academic class, so Studies is the one category no real source covers.
    Generating all 400 would mean grading the model largely on text produced by
    the same model family.

    PERSONAL IS NOW ALSO UNSOURCED, and deliberately not generated here. Enron
    was the intended source and its labels did not hold up (see the module
    docstring). Adding Personal to this generator is a one-word change, but it
    would take the set to 120 real against 360 synthetic -- three of four
    classes model-written -- which is a call for the team to make explicitly
    rather than something this script should do quietly.

    The label is ground truth by construction: we asked for a Studies email, so
    label_source is generation_prompt and label_confidence is strong. That is
    the one genuine advantage synthetic data has, and it is why this file
    records label provenance per row rather than for the set as a whole.
    """
    import random

    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, "backend", ".env"))
    sys.path.insert(0, ROOT)
    from backend.config import Config
    from backend.orchestrator.client import get_client

    settings = Config(require_llm=True)
    client = get_client(settings)
    rng = random.Random(20260826)  # fixed seed: the set is reproducible

    rows = []
    for category in categories:
        if category != "Studies":
            print(f"  refusing to generate {category!r}: real corpora already cover it.")
            print("  Generation fills gaps; it does not replace real mail (see data/README.md).")
            continue

        seen_subjects = set()
        attempts = 0
        while len(rows) < per_category and attempts < per_category * 3:
            attempts += 1
            scenario = rng.choice(STUDIES_SCENARIOS)
            sender_name, sender_email = rng.choice(STUDIES_SENDERS)
            tone = rng.choice(STUDIES_TONES)

            user_prompt = (
                "Write a university email about: " + scenario + "." + '\\n' +
                "It is from " + sender_name + " <" + sender_email + "> to a student." + '\\n' +
                "Tone: " + tone + "." + '\\n' +
                "Length: " + rng.choice(['3-4 sentences', '5-7 sentences', 'two short paragraphs']) + "."
            )

            try:
                payload = client.complete_json(
                    system=GENERATE_SYSTEM,
                    user=user_prompt,
                    schema_name="generated_email",
                    schema=GENERATED_SCHEMA,
                    purpose="dataset generation",
                    session_key="dataset-build",
                )
            except Exception as exc:
                print("")
                print(f"  generation failed on attempt {attempts}: {type(exc).__name__}")
                break

            subject = (payload.get("subject") or "").strip()
            body = _clean(payload.get("body") or "")
            if not subject or len(body) < 80:
                continue
            # Reject an exact subject repeat rather than shipping the duplicate.
            key = subject.lower()
            if key in seen_subjects:
                continue
            seen_subjects.add(key)

            rows.append({
                "id": _row_id("generated", f"{scenario}:{len(rows)}"),
                "provenance": "generated",
                "text_origin": "synthetic",
                "label_source": "generation_prompt",
                "label_confidence": "strong",
                "category": "Studies",
                "subject": subject[:300],
                "body": body,
                "sender": f"{sender_name} <{sender_email}>",
                "received_at": "",
                "source_ref": f"scenario={scenario}; tone={tone}",
            })
            if len(rows) % 10 == 0 or len(rows) == per_category:
                print(f"  generated {len(rows)}/{per_category}")

    print()
    _write(os.path.join(DATA, "generated.csv"), rows)

    # Hold this set to the standard the HuggingFace corpus failed. If the
    # generator is templating, the report should say so before a marker does.
    if rows:
        subjects = {r["subject"] for r in rows}
        shapes = {re.sub(r"[0-9]+", "#", r["subject"]) for r in rows}
        print(f"  diversity: {len(subjects)} distinct subjects, {len(shapes)} distinct shapes, over {len(rows)} rows")
        if len(subjects) < len(rows) * 0.9:
            print("  WARNING: subject reuse is high -- this set is templating.")
    return rows


# -------------------------------------------------------------------- merge


def _quality_rank(row):
    """Sort key deciding which rows survive when a class is over-supplied.

    The order encodes what makes a row worth keeping, best first:

      1. real text over synthetic  -- the whole argument of the dataset slide
      2. human labels over inferred ones
      3. strong confidence over weak

    So when the Promotions class holds both real Enron marketing and templated
    HuggingFace rows, the real ones are kept and the synthetic ones fall out on
    their merits rather than by deleting a file. Rebuild with a larger
    --per-class and the synthetic rows come back automatically.
    """
    origin = 0 if row.get("text_origin") == "real" else 1
    source = 0 if row.get("label_source") == "human" else 1
    confidence = 0 if row.get("label_confidence") == "strong" else 1
    return (origin, source, confidence, row.get("id", ""))


def merge(per_class=120, allow_unbalanced=False):
    rows = []
    for name in ("real_enron.csv", "real_huggingface.csv", "generated.csv"):
        path = os.path.join(DATA, name)
        if not os.path.exists(path):
            print(f"  skipping {name} (not built yet)")
            continue
        with open(path, encoding="utf-8") as f:
            rows.extend(list(csv.DictReader(f)))

    # Balance to per_class rows per category. An unbalanced set makes accuracy
    # a weighted average of class sizes, which reads as a model result and is
    # really an artefact of how much of each class was collected.
    by_category = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    # A class short of per_class used to produce a warning and an unbalanced
    # file anyway -- exactly the artefact the comment above warns about, and a
    # quiet change to what every benchmark run is measured against. It now
    # refuses, and says which per_class would be balanced.
    short = {c: len(items) for c, items in by_category.items() if len(items) < per_class}
    if short and not allow_unbalanced:
        largest = min(len(items) for items in by_category.values())
        sys.exit(
            f"  Refusing to write an unbalanced dataset: {short} short of {per_class}/class.\n"
            f"  Use --per-class {largest} for a balanced set, verify more rows for the short "
            f"class, or pass --allow-unbalanced if you really mean it."
        )

    balanced, dropped = [], {}
    for category, items in sorted(by_category.items()):
        items.sort(key=_quality_rank)
        keep = items[:per_class]
        balanced.extend(keep)
        if len(items) > per_class:
            dropped[category] = len(items) - len(keep)
        elif len(items) < per_class:
            print(f"  WARNING: {category} has only {len(items)} rows, short of {per_class}")

    if dropped:
        print(f"  balanced to {per_class}/class; dropped as surplus: {dropped}")

    rows = balanced
    _write(os.path.join(DATA, "dataset.csv"), rows)

    table = {}
    for row in rows:
        key = (row["provenance"], row.get("text_origin", "?"), row["category"])
        table[key] = table.get(key, 0) + 1
    print("")
    print("  provenance   text_origin  category     rows")
    for (provenance, origin, category), count in sorted(table.items()):
        print(f"    {provenance:12} {origin:11} {category:11} {count}")
    real = sum(c for (_, o, _), c in table.items() if o == "real")
    synthetic = sum(c for (_, o, _), c in table.items() if o == "synthetic")
    print("")
    print(f"  REAL email text:      {real}")
    print(f"  SYNTHETIC email text: {synthetic}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enron", action="store_true")
    parser.add_argument("--huggingface", action="store_true")
    parser.add_argument("--hf-file", default=None)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--per-category", type=int, default=120)
    parser.add_argument("--per-class", type=int, default=120,
                        help="rows per category in the merged dataset")
    parser.add_argument("--allow-unbalanced", action="store_true",
                        help="write the merged dataset even if a class is short of --per-class")
    parser.add_argument("--categories", default="Studies")
    args = parser.parse_args()

    if not any([args.enron, args.huggingface, args.generate, args.merge]):
        parser.print_help()
        return

    if args.enron:
        print("Enron:")
        build_enron(per_category=args.per_category)
    if args.huggingface:
        print("HuggingFace:")
        build_huggingface(args.hf_file, args.per_category)
    if args.generate:
        print("Generated:")
        build_generated(args.per_category, [c.strip() for c in args.categories.split(",")])
    if args.merge:
        print("Merge:")
        merge(args.per_class, allow_unbalanced=args.allow_unbalanced)


if __name__ == "__main__":
    main()
