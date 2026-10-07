"""Cold inbox load timing (NFR-01: under 5 seconds).

The slowest request the app makes routinely is the first GET /api/inbox after
sign-in: nothing is cached yet, so every email in the inbox is classified
inside that one request. This times exactly that, through the real Flask app,
the real route and the real model, on a fixture mailbox built from the
dataset's test split -- and the reload straight after it, which must cost no
model call.

    python -m eval.cold_load                                   # shipped vs batched, 5 trials each
    python -m eval.cold_load --settings 1x25,1x16,1x8 --out eval/data/nfr01/run.json

--settings is a list of BATCHxCONCURRENCY pairs: emails per model call
(CLASSIFY_BATCH_SIZE) and calls in flight at once (CLASSIFY_CONCURRENCY). The
settings are interleaved trial by trial, alternating direction, so drift in
the provider's latency over the run falls on all of them alike. One extra cold
load runs first and is reported apart: the process's first load also opens
the HTTPS connections that later loads reuse.

What it does not measure: the browser, the network between browser and
server, and the mail source (a fixture directory here, not Gmail). Those add
to what a user waits; they do not change how the settings compare.

Needs a real OPENAI_API_KEY (backend/.env). A 25-email inbox at one email per
call is 25 model calls per load. Nothing is printed from any email but counts.
"""

import argparse
import csv
import hashlib
import json
import logging
import os
import statistics
import sys
import tempfile
import time
from email.message import EmailMessage

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(ROOT, "eval", "data", "dataset.csv")
USER, PASSWORD = "timing@cold-load.local", "cold-load-local-only"


def _split_of(row_id):
    """The same dev/test assignment as eval.evaluate_classifier."""
    digest = hashlib.sha1(row_id.encode("utf-8")).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < 40 else "test"


def build_mailbox(directory, size):
    """`size` test-split emails, taken round-robin by class in a fixed order."""
    with open(DATASET, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if _split_of(r["id"]) == "test"]
    by_class = {}
    for r in sorted(rows, key=lambda r: hashlib.sha1(r["id"].encode("utf-8")).hexdigest()):
        by_class.setdefault(r["category"], []).append(r)
    classes = sorted(by_class)
    picked, turn = [], 0
    while len(picked) < size and any(by_class.values()):
        pool = by_class[classes[turn % len(classes)]]
        if pool:
            picked.append(pool.pop(0))
        turn += 1
    for n, r in enumerate(picked):
        message = EmailMessage()
        message["From"] = r["sender"] or "someone@example.com"
        message["To"] = USER
        message["Subject"] = r["subject"]
        message["Date"] = r["received_at"] or "Mon, 01 Sep 2026 09:00:00 +1000"
        message["Message-ID"] = f"<{r['id']}@cold-load.local>"
        message.set_content(r["body"])
        with open(os.path.join(directory, f"{n:03d}.eml"), "wb") as fh:
            fh.write(bytes(message))
    return len(picked)


def parse_settings(text):
    settings = []
    for item in text.split(","):
        batch, _, concurrency = item.strip().lower().partition("x")
        if not (batch.isdigit() and concurrency.isdigit() and int(batch) > 0 and int(concurrency) > 0):
            raise argparse.ArgumentTypeError(f"'{item}' is not BATCHxCONCURRENCY, e.g. 1x25")
        settings.append((f"b{batch}c{concurrency}", int(batch), int(concurrency)))
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--emails", type=int, default=25, help="inbox size (GMAIL_LIMIT's default is 25)")
    parser.add_argument("--trials", type=int, default=5, help="cold loads per setting")
    parser.add_argument("--settings", type=parse_settings, default=parse_settings("1x25,20x25"),
                        help="BATCHxCONCURRENCY pairs to compare (default: shipped 1x25 vs batched 20x25)")
    parser.add_argument("--out", default=None, help="write every trial to this JSON file")
    parser.add_argument("--force", action="store_true", help="allow --out to replace an existing file")
    args = parser.parse_args()
    if args.out and os.path.exists(args.out) and not args.force:
        sys.exit(f"{args.out} already exists, and it is the record of an earlier run. "
                 f"Choose a new --out, or pass --force.")

    with tempfile.TemporaryDirectory(prefix="cold_load_") as work:
        inbox, empty = os.path.join(work, "inbox"), os.path.join(work, "empty")
        os.makedirs(inbox)
        size = build_mailbox(inbox, args.emails)

        # Set before any backend import: Config reads the environment when it
        # is built. load_dotenv does not override, so .env supplies the model
        # key and nothing else here.
        os.environ.update({
            "EMAIL_SOURCE": "fixture",
            "EMAIL_FIXTURE_DIR": inbox,
            "EMAIL_INBOX_DIR": empty,
            "GMAIL_OWNER": "",
            "AUTH_USERS": json.dumps({USER: generate_password_hash(PASSWORD)}),
            "JWT_SECRET": "cold-load-local-only",
        })
        load_dotenv(os.path.join(ROOT, "backend", ".env"))
        sys.path.insert(0, ROOT)
        from backend.app import create_app
        from backend.config import Config
        from backend.orchestrator import cache as cache_module
        from backend.orchestrator.budget import get_budget

        logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s %(name)s] %(message)s")
        config = Config()
        client = create_app(config).test_client()
        target = config.latency_target_seconds

        def login():
            response = client.post("/api/auth/login", json={"email": USER, "password": PASSWORD})
            assert response.status_code == 200, response.status_code
            return {"Authorization": f"Bearer {response.get_json()['token']}"}

        def cold_load(batch, concurrency):
            config.classify_batch_size, config.classify_concurrency = batch, concurrency
            cache_module.clear_all()
            get_budget(config).reset()
            headers = login()
            start = time.perf_counter()
            response = client.get("/api/inbox", headers=headers)
            cold = time.perf_counter() - start
            start = time.perf_counter()
            again = client.get("/api/inbox", headers=headers)
            reload = time.perf_counter() - start
            groups = response.get_json().get("groups", {}) if response.status_code == 200 else {}
            return {"status": response.status_code, "cold_s": round(cold, 3),
                    "reload_s": round(reload, 3), "reload_status": again.status_code,
                    "emails": sum(len(v) for v in groups.values()),
                    "review": len(groups.get("Review", []))}

        print(f"model={config.openai_model}  inbox={size} emails  trials={args.trials} per setting  "
              f"target={target:g}s")
        first_name, first_batch, first_concurrency = args.settings[0]
        first = cold_load(first_batch, first_concurrency)
        print(f"  first load after start ({first_name}): {first['cold_s']:.2f}s "
              f"(opens the connections later loads reuse; not in the summary)", flush=True)

        results = {name: [] for name, _, _ in args.settings}
        for trial in range(args.trials):
            order = args.settings if trial % 2 == 0 else args.settings[::-1]
            for name, batch, concurrency in order:
                outcome = {"trial": trial + 1, **cold_load(batch, concurrency)}
                results[name].append(outcome)
                print(f"  trial {trial + 1} {name:8s} status={outcome['status']} cold={outcome['cold_s']:6.2f}s "
                      f"reload={outcome['reload_s'] * 1000:4.0f}ms emails={outcome['emails']} "
                      f"review={outcome['review']}", flush=True)

    print()
    for name, _, _ in args.settings:
        cold = [r["cold_s"] for r in results[name]]
        print(f"{name:8s} cold load: median {statistics.median(cold):.2f}s  min {min(cold):.2f}s  "
              f"max {max(cold):.2f}s  under {target:g}s: {sum(c < target for c in cold)}/{len(cold)}")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"model": config.openai_model, "inbox_emails": size, "trials": args.trials,
                       "target_seconds": target,
                       "settings": {name: {"classify_batch_size": b, "classify_concurrency": c}
                                    for name, b, c in args.settings},
                       "first_load": {"setting": first_name, **first},
                       "results": results}, fh, indent=2)
        print(f"\nEvery trial -> {args.out}")


if __name__ == "__main__":
    main()
