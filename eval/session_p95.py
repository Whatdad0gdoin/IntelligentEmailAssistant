"""NFR-01 as the RTM states it: p95 latency over 100 logged requests.

    python -m eval.session_p95 --out eval/data/nfr01/session_p95_<date>.json

The RTM's verification method for NFR-01 is "p95 latency under 5 s across 100
logged requests". The app keeps that log itself: middleware/timing.py records
every request into a ring of METRICS_WINDOW (100) entries, and GET
/api/metrics reports the nearest-rank p95 over it. This script fills that ring
with 100 requests through the real Flask app and the real model, then reads
the app's own report.

Every one of the 100 calls the model, and every cache is cleared before each
one, so none is a cached reload. That makes this the pessimistic version: a
real session is mostly cached reloads, which take milliseconds and would pull
the p95 down. The mix, interleaved in a fixed shuffled order:

    4  cold inbox loads (25 emails classified inside each request)
   40  summaries
   24  drafts (6 in each of the four tones)
   16  translations (8 Spanish, 8 Chinese Simplified)
   16  commands (typed text to an intent, as the command bar sends it)

The mailbox is the 25 test-split emails eval/cold_load.py uses. Signing in
happens once, before the 100, so the ring holds exactly them.

What it does not measure: the browser, the network between browser and
server, and the mail source (a fixture directory, not Gmail).

Needs a real OPENAI_API_KEY (backend/.env); about 200 model calls in all.
Nothing from any email is printed: counts, statuses and times only.
"""

import argparse
import json
import logging
import os
import random
import statistics
import sys
import tempfile
import time

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from eval.cold_load import ROOT, build_mailbox

USER, PASSWORD = "timing@session-p95.local", "session-p95-local-only"
COMMANDS = [
    "summarise the latest email",
    "read me the newest email",
    "draft a reply to the latest email",
    "what is the most recent email about",
]


def plan(seed=7):
    """The 100 requests, as (kind, n) pairs in a fixed shuffled order."""
    steps = ([("inbox", n) for n in range(4)] + [("summarise", n) for n in range(40)]
             + [("draft", n) for n in range(24)] + [("translate", n) for n in range(16)]
             + [("intent", n) for n in range(16)])
    random.Random(seed).shuffle(steps)
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=None, help="write every request and the report here")
    parser.add_argument("--force", action="store_true", help="allow --out to replace a file")
    args = parser.parse_args()
    if args.out and os.path.exists(args.out) and not args.force:
        sys.exit(f"{args.out} already exists, and it is the record of an earlier run. "
                 f"Choose a new --out, or pass --force.")

    with tempfile.TemporaryDirectory(prefix="session_p95_") as work:
        inbox, empty = os.path.join(work, "inbox"), os.path.join(work, "empty")
        os.makedirs(inbox)
        size = build_mailbox(inbox, 25)

        # Before any backend import: Config reads the environment when built.
        os.environ.update({
            "EMAIL_SOURCE": "fixture",
            "EMAIL_FIXTURE_DIR": inbox,
            "EMAIL_INBOX_DIR": empty,
            "GMAIL_OWNER": "",
            "AUTH_USERS": json.dumps({USER: generate_password_hash(PASSWORD)}),
            "JWT_SECRET": "session-p95-local-only",
            "ACCOUNTS_DB": os.path.join(work, "accounts.db"),
            "METRICS_WINDOW": "100",
        })
        load_dotenv(os.path.join(ROOT, "backend", ".env"))
        sys.path.insert(0, ROOT)
        from backend.adapters.email_source import get_email_source
        from backend.app import create_app
        from backend.config import Config
        from backend.orchestrator import cache as cache_module
        from backend.orchestrator.budget import get_budget
        from backend.orchestrator.preprocess import preprocess_email

        logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s %(name)s] %(message)s")
        config = Config()
        client = create_app(config).test_client()
        target = config.latency_target_seconds

        token = client.post("/api/auth/login", json={"email": USER, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {token.get_json()['token']}"}

        # Emails with text left after cleaning: an empty one answers 422 in a
        # millisecond without calling the model, which would flatter the p95.
        messages = get_email_source(config, USER).list_emails()
        usable = [m for m in messages if not preprocess_email(m, config.token_budget_chars).is_empty]
        candidates = [{"id": m.id, "sender_name": m.sender_name, "subject": m.subject,
                       "received_at": m.received_at} for m in messages]
        tones = ("neutral", "formal", "casual", "professional")

        def request(kind, n):
            email = usable[n % len(usable)]
            if kind == "inbox":
                return client.get("/api/inbox", headers=headers)
            if kind == "summarise":
                return client.post("/api/summarise", headers=headers, json={"email_id": email.id})
            if kind == "draft":
                return client.post("/api/draft", headers=headers,
                                   json={"email_id": email.id, "tone": tones[n % 4]})
            if kind == "translate":
                language = "Spanish" if n % 2 == 0 else "Chinese (Simplified)"
                return client.post("/api/translate", headers=headers,
                                   json={"email_id": email.id, "language": language})
            return client.post("/api/voice/intent", headers=headers,
                               json={"transcript": COMMANDS[n % len(COMMANDS)],
                                     "emails": candidates})

        print(f"model={config.openai_model}  mailbox={size} emails ({len(usable)} with text)  "
              f"target={target:g}s  window={config.metrics_window}")
        steps, records = plan(), []
        for i, (kind, n) in enumerate(steps, 1):
            cache_module.clear_all()          # every request a cache miss
            get_budget(config).reset()        # the session cap is not what is measured
            start = time.perf_counter()
            response = request(kind, n)
            seconds = time.perf_counter() - start
            records.append({"i": i, "kind": kind, "status": response.status_code,
                            "seconds": round(seconds, 3)})
            if i % 10 == 0:
                print(f"  {i}/100", flush=True)

        report = client.get("/api/metrics", headers=headers).get_json()

    overall = report["overall"]
    failures = [r for r in records if r["status"] != 200]
    print(f"\nGET /api/metrics over the last {report['window_size']} requests:")
    print(f"  overall  n={overall['count']}  p50={overall['p50_ms'] / 1000:.2f}s  "
          f"p95={overall['p95_ms'] / 1000:.2f}s  max={overall['max_ms'] / 1000:.2f}s  "
          f"over {target:g}s: {overall['over_target']}  p95 within target: "
          f"{report['p95_within_target']}")
    for route, block in sorted(report["routes"].items()):
        if block:
            print(f"  {route:34s} n={block['count']:3d}  p50={block['p50_ms'] / 1000:.2f}s  "
                  f"p95={block['p95_ms'] / 1000:.2f}s  max={block['max_ms'] / 1000:.2f}s")
    by_kind = {}
    for r in records:
        by_kind.setdefault(r["kind"], []).append(r["seconds"])
    print("\nClient-side, per kind (median / max seconds):")
    for kind, values in sorted(by_kind.items()):
        print(f"  {kind:10s} n={len(values):3d}  {statistics.median(values):.2f} / {max(values):.2f}")
    print(f"\nNon-200 responses: {len(failures)}"
          + (f" ({', '.join(sorted({str(f['status']) for f in failures}))})" if failures else ""))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"model": config.openai_model, "mailbox_emails": size,
                       "target_seconds": target, "metrics": report, "requests": records},
                      fh, indent=2)
        print(f"\nEvery request -> {args.out}")


if __name__ == "__main__":
    main()
