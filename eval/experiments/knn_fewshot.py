"""Retrieval-augmented few-shot classification: "it learns from your corrections".

    python -m eval.experiments.knn_fewshot --model gpt-4o-mini --split dev --k 0
    python -m eval.experiments.knn_fewshot --model gpt-4o-mini --split dev --k 4
    python -m eval.experiments.knn_fewshot --model gpt-4o-mini --split test --k 8 --pool 40

THE IDEA
Every email is shown the k most similar emails whose labels are already known,
as worked examples, before it is classified. In the product the labelled pool
is the user's own corrections: each email they move out of Review or re-file
becomes an example. So the classifier should get better with use, and the
--pool option measures exactly that -- a learning curve over how many emails a
user has corrected.

WHAT IS HELD CONSTANT
The unchanged classifier path (classify_emails, the evidence verifier, the 0.7
threshold) through eval/compare_models.run_classify. Only the user message
changes: prompts.classify_user is wrapped, inside this process only, to put an
examples block in front of the usual payload. Runs are one email per call (the
neighbours are per email), so k=0 is the matching zero-shot control: it
separates the effect of unbatching from the effect of the examples.

LEAKAGE GUARDS
- The pool is dev rows only. It never contains the email being classified
  (leave-one-out on dev) and never contains any test row.
- Examples are shown without ids.
- The evidence quote must still come from the email being classified. A quote
  copied from an example is not in the target email, so the unchanged verifier
  rejects it and the row goes to Review -- it can only cost accuracy, never
  inflate it.

PROTOCOL
k is chosen on dev, then frozen. Test is run once for the chosen k (and once
for k=0 as the control). The learning curve on test uses that frozen k.

Embeddings: OpenAI text-embedding-3-small ($0.02 per 1M tokens; the whole
dataset costs well under a cent). Cached outside the repository and rebuilt
when missing.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile

from backend.orchestrator import prompts
from backend.orchestrator.preprocess import preprocess
from eval import compare_models
from eval.evaluate_classifier import DATASET, _split_of

EMBED_MODEL = "text-embedding-3-small"
EMBED_PRICE_PER_1M = 0.02
CACHE = os.path.join(tempfile.gettempdir(), "ds25_knn_cache", f"{EMBED_MODEL}.json")
EXCERPT_CHARS = 400
POOL_SEED = "20261006"

EXAMPLES_HEADER = (
    "Examples of correctly labelled emails from this mailbox. They are here only to "
    "show how the categories are applied. Do NOT classify them and do NOT quote from "
    "them: the evidence must be copied word for word from the email you are asked to "
    "classify, below the examples."
)


def _embed_text(row):
    body = preprocess(row["body"], 12000).text[:2000]
    return f"From: {row.get('sender', '')}\nSubject: {row['subject']}\n{body}"


def load_embeddings(rows):
    cached = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cached = json.load(f)
    missing = [r for r in rows if r["id"] not in cached]
    if missing:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=2, timeout=60)
        tokens = 0
        for start in range(0, len(missing), 100):
            chunk = missing[start:start + 100]
            response = client.embeddings.create(model=EMBED_MODEL,
                                                input=[_embed_text(r) for r in chunk])
            tokens += response.usage.total_tokens
            for row, item in zip(chunk, response.data):
                cached[row["id"]] = item.embedding
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cached, f)
        print(f"embedded {len(missing)} emails: {tokens} tokens, "
              f"${tokens / 1e6 * EMBED_PRICE_PER_1M:.5f}")
    return cached


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def stratified_pool(dev_rows, size):
    """A deterministic, class-balanced subset of dev: 'a user who corrected N emails'."""
    if not size:
        return dev_rows
    by_class = {}
    for row in dev_rows:
        by_class.setdefault(row["category"], []).append(row)
    per_class = max(1, size // len(by_class))
    picked = []
    for label in sorted(by_class):
        ordered = sorted(by_class[label],
                         key=lambda r: hashlib.sha1(f"{POOL_SEED}:{r['id']}".encode()).hexdigest())
        picked += ordered[:per_class]
    return picked


def install_examples(k, pool_rows, vectors, rows_by_id):
    """Wrap prompts.classify_user so each single-email call carries its k neighbours."""
    original = prompts.classify_user
    pool_ids = [r["id"] for r in pool_rows]

    def with_examples(items):
        blocks = []
        for item in items:
            target = item["id"]
            candidates = [i for i in pool_ids if i != target]   # leave-one-out
            scored = sorted(candidates, key=lambda i: _cosine(vectors[target], vectors[i]),
                            reverse=True)[:k]
            for neighbour in scored:
                row = rows_by_id[neighbour]
                excerpt = preprocess(row["body"], 12000).text[:EXCERPT_CHARS]
                blocks.append(
                    f"<example label=\"{row['category']}\">\n"
                    f"From: {row.get('sender', '')}\nSubject: {row['subject']}\n"
                    f"Excerpt: {excerpt}\n</example>")
        if not blocks:
            return original(items)
        return EXAMPLES_HEADER + "\n\n" + "\n\n".join(blocks) + "\n\n" + original(items)

    prompts.classify_user = with_examples


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--k", type=int, required=True, help="0 = unbatched zero-shot control")
    parser.add_argument("--pool", type=int, default=0,
                        help="use a class-balanced subset of N dev rows as the labelled pool")
    parser.add_argument("--tag", default="r1")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    with open(DATASET, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows_by_id = {r["id"]: r for r in rows}
    dev_rows = [r for r in rows if _split_of(r["id"]) == "dev"]
    pool = stratified_pool(dev_rows, args.pool)
    assert all(_split_of(r["id"]) == "dev" for r in pool), "a test row leaked into the pool"

    if args.k == 0:
        run_name = f"{args.model}+unbatched"
    else:
        vectors = load_embeddings(rows)
        install_examples(args.k, pool, vectors, rows_by_id)
        run_name = f"{args.model}+knn{args.k}" + (f"-pool{args.pool}" if args.pool else "")

    compare_models.run_classify(
        args.model, args.split, args.tag, args.force, batch_size=1, run_name=run_name,
        extra_settings={"knn_k": args.k, "pool_size": len(pool), "embedding": EMBED_MODEL,
                        "pool_source": "dev split (leave-one-out on dev)"})


if __name__ == "__main__":
    main()
