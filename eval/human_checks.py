"""Two checks the RTM gives to a person, packaged so each takes a teammate minutes.

FR-06, tone. The RTM verifies tone by "blind review of 15 drafts, 80%
agreement". `fr06-build` drafts replies to 5 test-split emails in each of the
three named tones (formal, casual, professional), shuffles the 15, and writes
them to a sheet with the tone hidden. A teammate who did not build it reads
each draft and writes the tone they think it is. `fr06-score` compares their
answers with the key, kept in a separate file.

DR-01, labels. The RTM asks for a two-rater check on the labelled set.
`labels-build` writes 60 real emails (20 each of Work, Personal and
Promotions; Studies is generated, so its label is not in doubt) to a sheet
with the label hidden. A teammate who did not do the first labelling labels
them, from the labelling guide's definitions; `labels-score` reports
agreement and Cohen's kappa against the dataset's labels, and lists the
disagreements for discussion.

    python -m eval.human_checks fr06-build       # 15 model calls
    python -m eval.human_checks fr06-score
    python -m eval.human_checks labels-build     # no model calls
    python -m eval.human_checks labels-score

Sheets and keys go to eval/data/human_checks/. Open only the sheet: the key
is what the answers are scored against, and reading it ends the blindness.
The sheets are UTF-8 CSV with a byte-order mark, so Excel opens them cleanly.
"""

import argparse
import collections
import csv
import hashlib
import json
import os
import random
import sys

from eval.cold_load import ROOT

DATASET = os.path.join(ROOT, "eval", "data", "dataset.csv")
OUT = os.path.join(ROOT, "eval", "data", "human_checks")
FR06_TONES = ("formal", "casual", "professional")
REAL_CLASSES = ("Work", "Personal", "Promotions")
SEED = 3164


def _split_of(row_id):
    """The same dev/test assignment as eval.evaluate_classifier."""
    digest = hashlib.sha1(row_id.encode("utf-8")).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < 40 else "test"


def _rows():
    with open(DATASET, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _refuse_overwrite(*paths):
    for path in paths:
        if os.path.exists(path):
            sys.exit(f"{os.path.relpath(path, ROOT)} already exists. It may hold someone's "
                     f"answers; move it aside before building a new sheet.")


# --- FR-06: tone ---------------------------------------------------------------------


def fr06_build():
    sheet, key = os.path.join(OUT, "fr06_sheet.csv"), os.path.join(OUT, "fr06_key.csv")
    _refuse_overwrite(sheet, key)

    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, "backend", ".env"))
    sys.path.insert(0, ROOT)
    from backend.config import Config
    from backend.orchestrator.draft import draft_reply
    from backend.orchestrator.preprocess import preprocess_email
    from eval.evaluate_grounding import _as_source_email

    config = Config(require_llm=True, require_auth=False)
    rng = random.Random(SEED)
    candidates = [r for r in _rows() if _split_of(r["id"]) == "test"
                  and r["text_origin"] == "real"
                  and not preprocess_email(_as_source_email(r), config.token_budget_chars).is_empty]
    emails = rng.sample(candidates, 5)

    drafts = []
    for row in emails:
        for tone in FR06_TONES:
            result = draft_reply(_as_source_email(row), "", config, tone=tone)
            drafts.append({"email_id": row["id"], "subject": row["subject"],
                           "draft": result["draft"], "tone": tone})
            print(f"  drafted {len(drafts)}/15", flush=True)
    rng.shuffle(drafts)

    _write(sheet, ["n", "subject", "draft", "your_tone"],
           [{"n": i, "subject": d["subject"], "draft": d["draft"], "your_tone": ""}
            for i, d in enumerate(drafts, 1)])
    _write(key, ["n", "email_id", "tone"],
           [{"n": i, "email_id": d["email_id"], "tone": d["tone"]} for i, d in enumerate(drafts, 1)])
    print(f"\nSheet -> {os.path.relpath(sheet, ROOT)}")
    print("For each draft, write formal, casual or professional in your_tone. Do not open the key.")


def fr06_score():
    sheet = {r["n"]: r for r in _read(os.path.join(OUT, "fr06_sheet.csv"))}
    key = {r["n"]: r for r in _read(os.path.join(OUT, "fr06_key.csv"))}
    answered = {n: r["your_tone"].strip().lower() for n, r in sheet.items()
                if r["your_tone"].strip()}
    if len(answered) < len(key):
        sys.exit(f"{len(key) - len(answered)} of {len(key)} drafts have no answer yet.")
    unknown = sorted({a for a in answered.values() if a not in FR06_TONES})
    if unknown:
        sys.exit(f"Answers must be one of {', '.join(FR06_TONES)}; found: {', '.join(unknown)}")

    hits = sum(answered[n] == key[n]["tone"] for n in key)
    confusion = collections.Counter((key[n]["tone"], answered[n]) for n in key)
    print(f"FR-06 blind tone review: {hits}/{len(key)} = {hits / len(key):.1%} agreement "
          f"(target 80%): {'MET' if hits / len(key) >= 0.8 else 'NOT MET'}")
    print("\nrequested -> recognised")
    for tone in FR06_TONES:
        row = "  ".join(f"{t}: {confusion[(tone, t)]}" for t in FR06_TONES)
        print(f"  {tone:12s} {row}")
    _save("fr06_result.json", {"agreement": hits / len(key), "agreed": hits, "n": len(key),
                               "confusion": {f"{a}->{b}": c for (a, b), c in confusion.items()}})


# --- DR-01: a second rater --------------------------------------------------------------


def labels_build():
    sheet, key = os.path.join(OUT, "labels_sheet.csv"), os.path.join(OUT, "labels_key.csv")
    _refuse_overwrite(sheet, key)
    rng = random.Random(SEED)
    rows = [r for r in _rows() if r["text_origin"] == "real"]
    picked = []
    for label in REAL_CLASSES:
        picked += rng.sample([r for r in rows if r["category"] == label], 20)
    rng.shuffle(picked)

    _write(sheet, ["n", "sender", "subject", "body", "your_label"],
           [{"n": i, "sender": r["sender"], "subject": r["subject"], "body": r["body"][:3000],
             "your_label": ""} for i, r in enumerate(picked, 1)])
    _write(key, ["n", "id", "label"],
           [{"n": i, "id": r["id"], "label": r["category"]} for i, r in enumerate(picked, 1)])
    print(f"Sheet -> {os.path.relpath(sheet, ROOT)}: 60 emails.")
    print(f"For each, write {', '.join(REAL_CLASSES)} in your_label, using the labelling guide's "
          f"definitions. Do not open the key.")


def labels_score():
    sheet = {r["n"]: r for r in _read(os.path.join(OUT, "labels_sheet.csv"))}
    key = {r["n"]: r for r in _read(os.path.join(OUT, "labels_key.csv"))}
    answered = {n: r["your_label"].strip().capitalize() for n, r in sheet.items()
                if r["your_label"].strip()}
    if len(answered) < len(key):
        sys.exit(f"{len(key) - len(answered)} of {len(key)} emails have no label yet.")
    unknown = sorted({a for a in answered.values() if a not in REAL_CLASSES})
    if unknown:
        sys.exit(f"Labels must be one of {', '.join(REAL_CLASSES)}; found: {', '.join(unknown)}")

    n = len(key)
    observed = sum(answered[i] == key[i]["label"] for i in key) / n
    first = collections.Counter(key[i]["label"] for i in key)
    second = collections.Counter(answered.values())
    expected = sum(first[c] * second[c] for c in REAL_CLASSES) / (n * n)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    print(f"DR-01 second rater: agreement {observed:.1%} on {n} real emails, "
          f"Cohen's kappa {kappa:.2f}")
    disagreements = [(i, key[i]["id"], key[i]["label"], answered[i])
                     for i in sorted(key, key=int) if answered[i] != key[i]["label"]]
    if disagreements:
        print("\nDisagreements (row, id, dataset label, second rater), to discuss and settle:")
        for i, row_id, a, b in disagreements:
            print(f"  {i:>3}  {row_id}  {a} vs {b}")
    _save("labels_result.json", {"agreement": observed, "cohens_kappa": kappa, "n": n,
                                 "disagreements": [{"id": d[1], "dataset": d[2], "second_rater": d[3]}
                                                   for d in disagreements]})


def _save(name, data):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nResult -> {os.path.relpath(path, ROOT)}")


def main():
    commands = {"fr06-build": fr06_build, "fr06-score": fr06_score,
                "labels-build": labels_build, "labels-score": labels_score}
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(commands))
    commands[parser.parse_args().command]()


if __name__ == "__main__":
    main()
