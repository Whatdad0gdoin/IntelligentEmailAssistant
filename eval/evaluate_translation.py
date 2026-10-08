"""Figures preserved in translation (FR-07).

Translates the subject and cleaned body of N emails from the test split of
eval/data/dataset.csv into one language, through the same translate_email the
/api/translate route calls -- same prompt, schema, pieces, retry and check, and
the real model -- and reports how often every number, link and email address
came through:

    preserved rate = translations with no flags / translations produced

WHAT THIS IS NOT

It is not a translation quality score. A translation can carry every figure
across and still say something else, and this dataset holds no reference
translations to score adequacy or fluency against. What it measures is the one
property the backend checks in any pair of languages: no number, link or
address was invented or lost on the way through. A flag is evidence of a
problem, not proof of one -- a month name written as a number is flagged and
may be fine -- so the flagged claims are listed by kind for a person to read.

A translation that could not be produced (a 502, a timeout) is a production
failure. It is counted apart and never folded into the rate.

    python -m eval.evaluate_translation --language Spanish --limit 40 \\
        --out eval/data/translation/spanish_test40.csv
    python -m eval.evaluate_translation --language "Chinese (Simplified)" --limit 40 \\
        --out eval/data/translation/chinese-simplified_test40.csv

Nothing from any email or any translation is printed or written: ids, counts,
timings and the flags themselves (the number, link or address, and why). --out
refuses to replace an existing file unless --force is given. --max-usd stops
the run once the estimated spend passes it.
"""

import argparse
import collections
import csv
import logging
import os
import re
import statistics
import sys
import time

from dotenv import load_dotenv

# Before the Config import: Config reads the environment when it is built, and
# backend/.env is where the key lives (the same order as the other harnesses).
load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", ".env"))

from backend.config import Config  # noqa: E402
from backend.orchestrator import translate as translate_module  # noqa: E402
from backend.orchestrator.preprocess import preprocess_email  # noqa: E402
from backend.orchestrator.schemas import LANGUAGES  # noqa: E402
from backend.orchestrator.translate import (  # noqa: E402
    EmptyEmailError,
    _inventory,
    split_text,
    translate_email,
)
from eval.build_dataset import DATA, ROOT  # noqa: E402
from eval.evaluate_classifier import _load  # noqa: E402
from eval.evaluate_grounding import _as_source_email  # noqa: E402
from eval.providers import PRICES, cost_usd  # noqa: E402

DATASET = os.path.join(DATA, "dataset.csv")

# Every reason check_translation can give, and its column in --out.
REASONS = {
    "number not in the original": "flags_number_added",
    "number missing from the translation": "flags_number_missing",
    "link not in the original": "flags_link_added",
    "link missing from the translation": "flags_link_missing",
    "email address not in the original": "flags_address_added",
    "email address missing from the translation": "flags_address_missing",
}


class TokenTally(logging.Handler):
    """Adds up the token counts client.py logs for every successful call.

    The log line carries counts only -- client.py never logs a prompt or a
    response -- so reading it here costs no NFR-03 ground. A call that failed
    logged no usage, so a run with failures is slightly under-counted, and the
    report says so.
    """

    _USAGE = re.compile(r"prompt=(\d+), completion=(\d+) tokens")

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.prompt = 0
        self.completion = 0
        self.calls = 0

    def emit(self, record):
        match = self._USAGE.search(record.getMessage())
        if match:
            self.prompt += int(match.group(1))
            self.completion += int(match.group(2))
            self.calls += 1


def _translate_row(row, language, config, tally):
    """One email through the real path. Returns a record with no text in it."""
    email = _as_source_email(row)
    cleaned = preprocess_email(email, config.token_budget_chars)
    subject = (email.subject or "").strip()
    urls, addresses, numbers = _inventory(f"{subject}\n{cleaned.text}")
    record = {
        "id": row["id"],
        "category": row["category"],
        "provenance": row["provenance"],
        "text_origin": row["text_origin"],
        "language": language,
        "model": config.openai_model,
        "source_chars": len(cleaned.text),
        "pieces": len(split_text(cleaned.text)) if cleaned.text else 0,
        "numbers_in_original": len(numbers),
        "links_in_original": len(urls),
        "addresses_in_original": len(addresses),
    }
    before = (tally.prompt, tally.completion)
    started = time.perf_counter()
    try:
        result = translate_email(email, language, config)
    except EmptyEmailError:
        # Nothing left once quoting and footers are stripped: the app answers
        # 422 before any model call, as it does for a summary. Not a failure of
        # translation, and not something the rate can say anything about.
        record.update(status="empty", error="EmptyEmailError")
    except Exception as exc:
        # The type only: an exception string is not a place to look for text,
        # and this file must not become one.
        record.update(status="failed", error=type(exc).__name__)
    else:
        flags = result["ungrounded_flags"]
        kinds = collections.Counter(flag["reason"] for flag in flags)
        record.update(
            status="ok",
            error="",
            translation_chars=len(result["translation"]),
            # Identical to the original means nothing was translated -- right
            # only when the email was already in the target language.
            unchanged=result["translation"].strip() == cleaned.text.strip(),
            grounded=result["grounded"],
            flag_count=len(flags),
            **{column: kinds.get(reason, 0) for reason, column in REASONS.items()},
            flags="; ".join(f"{flag['claim']} ({flag['reason']})" for flag in flags)[:300],
            _flags=flags,
        )
    record["seconds"] = round(time.perf_counter() - started, 2)
    record["prompt_tokens"] = tally.prompt - before[0]
    record["completion_tokens"] = tally.completion - before[1]
    return record


def _estimate(model, tally):
    if model not in PRICES:
        return None
    return cost_usd(model, tally.prompt, tally.completion)


def _report(records, language, config, tally, elapsed, stopped_early):
    produced = [r for r in records if r["status"] == "ok"]
    empty = [r for r in records if r["status"] == "empty"]
    failed = [r for r in records if r["status"] == "failed"]
    clean = [r for r in produced if r["grounded"]]

    print("\n" + "=" * 72)
    print(f"TRANSLATION  (FR-07)   language={language}  model={config.openai_model}")
    print(f"\n  attempted          {len(records)}")
    print(f"  nothing to translate once cleaned (a 422, no model call)  {len(empty)}")
    print(f"  produced           {len(produced)}")
    print(f"  failed outright    {len(failed)}"
          f"{'  <-- not counted in the rate below' if failed else ''}")
    rate = len(clean) / len(produced) if produced else 0.0
    print(f"\n  NUMBERS AND LINKS PRESERVED  {rate:.1%}  "
          f"({len(clean)} clean / {len(produced)} produced)")
    print(f"  flagged translations         {len(produced) - len(clean)}")

    # The denominator that says whether the rate means anything: a rate over
    # emails with no numbers, links or addresses in them checks nothing.
    numbers = sum(r["numbers_in_original"] for r in produced)
    links = sum(r["links_in_original"] for r in produced)
    addresses = sum(r["addresses_in_original"] for r in produced)
    checkable = sum(1 for r in produced
                    if r["numbers_in_original"] or r["links_in_original"] or r["addresses_in_original"])
    print(f"\n  checked: {numbers} numbers, {links} links and {addresses} email addresses "
          f"in {len(produced)} originals")
    print(f"  originals with at least one checkable item: {checkable}/{len(produced)}"
          f"{'   <-- rate is vacuous below half' if checkable < len(produced) / 2 else ''}")

    kinds = collections.Counter()
    claims = collections.Counter()
    for record in produced:
        for flag in record["_flags"]:
            kinds[flag["reason"]] += 1
            claims[(flag["claim"][:40], flag["reason"])] += 1
    if kinds:
        print("\n  Flags by kind")
        for reason, count in kinds.most_common():
            print(f"    {count:>4}  {reason}")
        print("\n  Most frequently flagged")
        for (claim, reason), count in claims.most_common(10):
            print(f"    {count:>4}  {claim!r}  ({reason})")

    by_category = collections.defaultdict(list)
    for record in produced:
        by_category[record["category"]].append(record)
    print(f"\n  {'category':14}{'n':>4}{'preserved':>11}")
    for category in sorted(by_category):
        group = by_category[category]
        share = sum(1 for r in group if r["grounded"]) / len(group)
        print(f"  {category:14}{len(group):>4}{share:>10.1%}")

    unchanged = sum(1 for r in produced if r["unchanged"])
    pieced = sum(1 for r in produced if r["pieces"] > 1)
    print(f"\n  returned unchanged (identical to the original): {unchanged}")
    print(f"  long enough to be cut into pieces: {pieced}")
    if produced:
        seconds = [r["seconds"] for r in produced]
        print(f"  time per email: median {statistics.median(seconds):.1f}s, "
              f"max {max(seconds):.1f}s; {elapsed:.0f}s in all")

    if failed:
        print("\n  Production failures (reported apart, never as flags)")
        for kind, count in collections.Counter(r["error"] for r in failed).most_common():
            print(f"    {count:>4}  {kind}")

    cost = _estimate(config.openai_model, tally)
    print(f"\n  tokens: {tally.prompt:,} prompt + {tally.completion:,} completion "
          f"over {tally.calls} calls" + (" (failed calls not counted)" if failed else ""))
    if cost is None:
        print(f"  cost: no list price for {config.openai_model} in eval/providers.py")
    else:
        print(f"  estimated cost: US${cost:.4f} at list price")
    if stopped_early:
        print("\n  STOPPED EARLY at --max-usd. This run is incomplete; do not quote it.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", required=True, choices=LANGUAGES,
                        help="target language, exactly as the API takes it")
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--limit", type=int, default=40,
                        help="emails to translate, balanced across categories; "
                             "one model call each, more for a long one")
    parser.add_argument("--out", default=None,
                        help="write one row per email (ids, counts, flags; no text) to a CSV")
    parser.add_argument("--force", action="store_true", help="allow --out to replace an existing file")
    parser.add_argument("--max-usd", type=float, default=0.50,
                        help="stop once the estimated spend passes this (default 0.50)")
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        sys.exit(f"Missing {args.dataset}. Run: python -m eval.build_dataset --merge")
    if args.out and os.path.exists(args.out) and not args.force:
        # Checked before any model call: the file may be the only record of a
        # run quoted in eval/BENCHMARKS.md.
        sys.exit(f"Refusing to overwrite {args.out}: it may be the only record of an "
                 f"earlier run. Choose a new --out, or pass --force.")

    try:
        config = Config(require_llm=True, require_auth=False)
    except Exception as exc:
        sys.exit(f"{exc}\n\nThis evaluation calls the real model. Set OPENAI_API_KEY "
                 f"in backend/.env and run it again.")

    logging.basicConfig(level=logging.WARNING, format="  [%(levelname)s %(name)s] %(message)s")
    tally = TokenTally()
    client_log = logging.getLogger("backend.orchestrator.client")
    client_log.setLevel(logging.INFO)
    client_log.addHandler(tally)
    client_log.propagate = False   # the tally reads the INFO lines; the console need not
    # Warnings from the client still matter (a retry, a rate limit): echo them.
    echo = logging.StreamHandler()
    echo.setLevel(logging.WARNING)
    echo.setFormatter(logging.Formatter("  [%(levelname)s %(name)s] %(message)s"))
    client_log.addHandler(echo)

    rows = _load(args.dataset, args.limit, args.split)
    print(f"Translating {len(rows)} emails ({args.split} split) into {args.language} "
          f"with {config.openai_model}.")
    print(f"  temperature={config.openai_temperature}  timeout={config.openai_timeout_seconds:g}s  "
          f"body budget={config.token_budget_chars} chars  "
          f"piece size={translate_module.CHUNK_CHARS} chars  max spend=US${args.max_usd:.2f}")

    records, stopped_early = [], False
    started = time.perf_counter()
    for index, row in enumerate(rows, 1):
        records.append(_translate_row(row, args.language, config, tally))
        if index % 10 == 0 or index == len(rows):
            print(f"  {index}/{len(rows)}", flush=True)
        cost = _estimate(config.openai_model, tally)
        if cost is not None and cost > args.max_usd:
            stopped_early = True
            print(f"  stopping: estimated spend US${cost:.4f} passed --max-usd {args.max_usd:.2f}")
            break
    _report(records, args.language, config, tally, time.perf_counter() - started, stopped_early)

    print("\nQuote the preserved rate with the language, the model, the sample size and")
    print("the flags by kind. It is not a quality score: it says the figures, links and")
    print("addresses came through, not that the translation is right.")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        columns = ["id", "category", "provenance", "text_origin", "language", "model", "status",
                   "error", "source_chars", "translation_chars", "pieces", "unchanged",
                   "numbers_in_original", "links_in_original", "addresses_in_original",
                   "grounded", "flag_count", *REASONS.values(), "flags",
                   "seconds", "prompt_tokens", "completion_tokens"]
        with open(args.out, "w" if args.force else "x", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        print(f"\nPer-email results -> {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
