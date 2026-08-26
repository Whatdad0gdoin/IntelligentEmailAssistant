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
in it is Work. A handful of folders (`myfriends`, `personalfolder`, `personal`)
genuinely indicate Personal.

It supplies essentially ZERO Promotions and ZERO Studies. Any claim that Enron
provides all four classes does not survive contact with the data. That is why
the generated set exists: to fill the classes real corpora do not cover, not to
replace them.
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
ENRON_FOLDER_LABELS = {
    "myfriends": ("Personal", "weak"),
    "personalfolder": ("Personal", "weak"),
    "personal": ("Personal", "weak"),
    "friends": ("Personal", "weak"),
    "family": ("Personal", "weak"),
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

    counts = {"Work": 0, "Personal": 0}
    rows = []
    scanned = 0

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
            folder = parts[2].lower()
            label = ENRON_FOLDER_LABELS.get(folder)
            if label is None:
                continue
            category, confidence = label
            if counts.get(category, 0) >= per_category:
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

    print(f"  scanned {scanned} archive entries")
    print(f"  collected {counts}")
    _write(os.path.join(DATA, "real_enron.csv"), rows)
    return rows


# --------------------------------------------------------------- huggingface


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
    real corpora supply Work, Personal and Promotions, and generation "fills a
    gap, not the test". Enron contains no academic mail and the HuggingFace
    taxonomy has no academic class, so Studies is the one category no real
    source covers. Generating all 400 would mean grading the model largely on
    text produced by the same model family.

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


def merge():
    rows = []
    for name in ("real_enron.csv", "real_huggingface.csv", "generated.csv"):
        path = os.path.join(DATA, name)
        if not os.path.exists(path):
            print(f"  skipping {name} (not built yet)")
            continue
        with open(path, encoding="utf-8") as f:
            rows.extend(list(csv.DictReader(f)))

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
        merge()


if __name__ == "__main__":
    main()
