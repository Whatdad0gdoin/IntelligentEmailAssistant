"""Find Enron messages likely to be personal correspondence, for hand labelling.

THE PROBLEM WITH THE OBVIOUS APPROACH

The tempting filter is a keyword list -- party, wedding, birthday, dinner, mom.
It would work, and it would ruin the dataset. Selecting Personal rows by the
words that make an email obviously personal produces a Personal class made
entirely of easy cases, and a classifier scored on it looks better than it is.
The label would effectively be baked into the selection.

So the filters here are STRUCTURAL. They describe the shape of a message --
who sent it, how many people got it, how deep the forward chain runs -- and
none of them encode the answer:

  1. Consumer mail domain    hotmail, yahoo, juno, aol, rr.com, ...
  2. Few recipients          conversations, not distribution lists
  3. Not an automated sender no.address@, announcement.*, payroll.*, ...
  4. Plausible body length   long enough to judge, short enough to be real

These correlate with personal mail without defining it. Plenty of survivors are
Work -- recruiters emailing from Yahoo, vendors on AOL, industry newsletters --
which is exactly the property a keyword filter would destroy. The classifier
still has to do real work on the result.

WHAT THIS COSTS, AND IT MUST BE IN THE REPORT

This is not a random sample, so the Personal class it yields is a defined
subpopulation: *personal mail arriving at a corporate inbox, usually from an
outside consumer address*. Personal mail between two colleagues on internal
addresses is systematically under-represented, because filter 1 cannot see it.

The honest alternative is random sampling, which at roughly 5% Personal density
would mean hand-labelling ~2,400 messages to reach 120. That is the trade being
made: a documented selection bias in exchange for a feasible amount of reading.
Report it as a limitation; do not describe this class as a random sample of
Enron personal mail, because it is not one.

    python -m eval.extract_personal_candidates --limit 500
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

from eval.build_dataset import ENRON_ARCHIVE, DATA, ROOT, _clean

OUT_PATH = os.path.join(DATA, "personal_candidates.csv")

OUT_FIELDS = [
    "row", "verified", "proposed_category", "confidence", "rationale",
    "signals", "folder", "sender", "recipients", "subject", "body_preview",
    "id", "source_ref",
]

# Consumer mail providers, as they appeared around 2000-2002. A message from
# one of these into a corporate mailbox is far more likely to be personal --
# but plenty are recruiters and vendors, which is the point.
CONSUMER_DOMAINS = frozenset("""
hotmail.com yahoo.com aol.com juno.com msn.com earthlink.net mindspring.com
attbi.com flash.net prodigy.net compuserve.com excite.com netzero.net
bellsouth.net comcast.net sbcglobal.net pacbell.net gte.net home.com
worldnet.att.net swbell.net rr.com houston.rr.com mac.com email.msn.com
ix.netcom.com airmail.net ev1.net pdq.net sprintmail.com hotmail.co.uk
""".split())

# Internal addresses that only ever send bulk or automated mail.
AUTOMATED = re.compile(
    r"(?i)^(no\.?address|announcement|40enron|40ees|payroll|chairman|outlook\.team|"
    r"elm\.team|administration|parking|integrated\.solutions|enron\.announcements|"
    r"perfmgmt|ubsw|postmaster|mailer-daemon|root|custserv|orders|noreply|no-reply)"
)

MAX_RECIPIENTS = 4
MIN_BODY = 120
MAX_BODY = 4000
MAX_FORWARD_DEPTH = 2

_ORIGINAL = re.compile(r"(?i)-{2,}\s*original message|^\s*forwarded by", re.MULTILINE)


def _domain(address):
    return address.split("@")[-1].strip(">").lower() if "@" in (address or "") else ""


def _local(address):
    return address.split("@")[0].strip("<").lower() if "@" in (address or "") else ""


def _recipient_count(message):
    total = 0
    for header in ("To", "Cc", "Bcc"):
        value = message.get(header) or ""
        if value.strip():
            total += len([p for p in value.split(",") if p.strip()])
    return total


_LETTERS = re.compile(r"[^a-z ]+")


def _content_key(subject, body):
    """Dedupe key. The corpus stores the same message in many mailboxes.

    Keyed on words 25-85, skipping the opening. An earlier version hashed the
    first 300 characters and let 143 copies of one advocacy form letter into a
    500-row pool -- every copy opened with the sender's own name and postal
    address, so the openings differed while the letter beneath was identical.

    Skipping a fixed number of *words* rather than characters is what makes it
    work: address blocks vary in length, so a character window drifts out of
    alignment and the copies hash apart again (measured: character window 143
    copies -> 50 keys; word window -> 11). Digits and punctuation are stripped
    so a form letter differing only by a reference number stays one message.
    """
    words = _LETTERS.sub("", " ".join(body.lower().split())).split()
    window = " ".join(words[25:85]) or " ".join(words[:60])
    return hashlib.sha1(
        f"{subject.strip().lower()}|{window}".encode("utf-8", "replace")
    ).hexdigest()


def score(message, body, folder):
    """Structural signals only. Returns (score, [signal names])."""
    sender = (message.get("From") or "").strip()
    domain = _domain(sender)
    signals = []
    points = 0

    if AUTOMATED.match(_local(sender)):
        return -1, ["automated_sender"]

    if domain in CONSUMER_DOMAINS:
        points += 3
        signals.append("consumer_domain")

    recipients = _recipient_count(message)
    if 1 <= recipients <= 2:
        points += 2
        signals.append("few_recipients")
    elif recipients > MAX_RECIPIENTS:
        return -1, ["mass_distribution"]

    depth = len(_ORIGINAL.findall(body))
    if depth > MAX_FORWARD_DEPTH:
        return -1, ["deep_forward_chain"]

    if folder in ("personal", "personalfolder", "myfriends", "friends", "family"):
        points += 2
        signals.append("personal_folder")

    # A message that is neither from a consumer domain nor in a personal folder
    # is almost certainly internal business mail; not worth a reviewer's time.
    if "consumer_domain" not in signals and "personal_folder" not in signals:
        return -1, ["internal_business"]

    return points, signals


def extract(limit, scan_limit):
    if not os.path.exists(ENRON_ARCHIVE):
        sys.exit(
            f"Missing {ENRON_ARCHIVE}.\n"
            "Download it first:\n"
            "  curl -L -o eval/data/raw/enron_mail_20150507.tar.gz \\\n"
            "    https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz"
        )

    # Rows already proposed in the first pass -- do not offer them again.
    already = set()
    review = os.path.join(DATA, "review_enron_personal.csv")
    if os.path.exists(review):
        with open(review, encoding="utf-8") as f:
            already = {r["id"] for r in csv.DictReader(f)}

    seen_content = set()
    candidates = []
    scanned = 0
    kept_rejected = {}

    with tarfile.open(ENRON_ARCHIVE, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            scanned += 1
            if scanned > scan_limit or len(candidates) >= limit * 3:
                break
            if scanned % 50000 == 0:
                print(f"    scanned {scanned:,}, kept {len(candidates)}", flush=True)

            parts = member.name.split("/")
            if len(parts) < 4 or parts[0] != "maildir":
                continue
            folder = parts[2].lower()

            handle = tar.extractfile(member)
            if handle is None:
                continue
            try:
                message = email.message_from_binary_file(handle, policy=policy.default)
            except Exception:
                continue

            subject = (message.get("Subject") or "").strip()
            if not subject:
                continue
            body_part = message.get_body(preferencelist=("plain",))
            try:
                body = _clean(body_part.get_content() if body_part else "")
            except Exception:
                continue
            if not (MIN_BODY <= len(body) <= MAX_BODY):
                continue

            points, signals = score(message, body, folder)
            if points < 0:
                kept_rejected[signals[0]] = kept_rejected.get(signals[0], 0) + 1
                continue

            key = _content_key(subject, body)
            if key in seen_content:
                continue
            seen_content.add(key)

            row_id = f"enron-{hashlib.sha1(member.name.encode()).hexdigest()[:12]}"
            if row_id in already:
                continue

            candidates.append({
                "points": points,
                "signals": "+".join(signals),
                "folder": folder,
                "id": row_id,
                "source_ref": member.name,
                "sender": (message.get("From") or "").strip()[:200],
                "recipients": _recipient_count(message),
                "subject": subject[:300],
                "body": body,
            })

    candidates.sort(key=lambda c: -c["points"])
    candidates = candidates[:limit]

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        for index, c in enumerate(candidates, 1):
            writer.writerow({
                "row": index,
                "verified": "",
                "proposed_category": "",
                "confidence": "",
                "rationale": "",
                "signals": c["signals"],
                "folder": c["folder"],
                "sender": c["sender"],
                "recipients": c["recipients"],
                "subject": c["subject"],
                "body_preview": " ".join(c["body"].split())[:300],
                "id": c["id"],
                "source_ref": c["source_ref"],
            })

    print(f"  scanned {scanned:,} archive entries")
    print(f"  rejected: {kept_rejected}")
    print(f"  wrote {len(candidates)} candidates -> {os.path.relpath(OUT_PATH, ROOT)}")

    # Full bodies alongside, for the labelling pass.
    full = os.path.join(DATA, "personal_candidates_bodies.csv")
    with open(full, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["row", "id", "source_ref", "sender", "recipients",
                           "subject", "body", "signals", "folder"])
        writer.writeheader()
        for index, c in enumerate(candidates, 1):
            writer.writerow({
                "row": index, "id": c["id"], "source_ref": c["source_ref"],
                "sender": c["sender"], "recipients": c["recipients"],
                "subject": c["subject"], "body": c["body"],
                "signals": c["signals"], "folder": c["folder"],
            })
    print(f"  wrote full bodies -> {os.path.relpath(full, ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--scan-limit", type=int, default=600_000)
    args = parser.parse_args()
    extract(args.limit, args.scan_limit)


if __name__ == "__main__":
    main()
