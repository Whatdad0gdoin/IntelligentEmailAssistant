# Benchmark runs

Every measured result, in the order it was produced. Numbers are copied from the
runs named beside them — nothing here is estimated.

All runs use `temperature=0` and `--batch-size 20`. See
[Run-to-run variance](#run-to-run-variance) before quoting any figure to more
than one decimal place.

---

## Headline figures

Measured on the **held-out test split** with the shipped configuration
(`gpt-4o-mini`, as set in `backend/.env`):

| Requirement | Metric | Result |
|---|---|---|
| **FR-02** categorisation | accuracy (test split, n=266) | **83.0%** |
| | — on real email only | **78.1%** |
| **FR-01** summarisation | groundedness rate | **93.0%** |
| **FR-03** draft reply | groundedness rate | **97.4%** |
| FR-05 voice intent | dispatch accuracy | not yet run |
| NFR-01 latency | p95 | not yet instrumented |

Categorisation is the only one of these that is an accuracy. Summarisation and
drafting have no single correct output to score against, so they use
groundedness — see [Why not ROUGE](#why-not-rouge).

---

## The dataset these run against

`eval/data/dataset.csv` — 480 rows, balanced 120 per class.

| | rows |
|---|---|
| Work / Personal / Promotions / Studies | 120 each |
| **real** email text | **360** |
| synthetic email text | 120 |
| `label_source = human` (verified row by row) | 240 |
| `label_source = generation_prompt` | 120 |
| `label_source = folder_heuristic` (weak) | 120 |

Split for tuning: **dev 214 / test 266**, assigned deterministically by hashing
the row id (40% dev). Every prompt and model choice below was made on dev. The
reported figure was measured on test.

---

## FR-02 — Categorisation accuracy

### Why three numbers, not one

`Review` is an abstention, not a wrong answer: the classifier routes an email
there when its quoted evidence fails verification or its confidence is below
threshold. So each run reports:

- **coverage** — share given a real category rather than Review
- **accuracy** — correct, over covered rows only
- **strict** — Review counted as wrong

Quote all three. Accuracy alone hides how often it declined; coverage alone
hides whether the answers were any good.

### Run history

```bash
python -m eval.evaluate_classifier --split dev          # tuning runs
python -m eval.evaluate_classifier --split test         # reported figure
```

| # | Model | Change under test | Split | n | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|---|---|---|---|
| 1 | gpt-4o-mini | baseline | all | 480 | 82.5% | 77.3% | 63.7% | 0.685 |
| 2 | gpt-4o-mini | + evidence punctuation fix | all | 480 | 88.3% | 75.5% | 66.7% | 0.701 |
| 3 | gpt-4o-mini | baseline on dev | dev | 214 | 92.1% | 70.1% | 64.5% | 0.668 |
| 4 | gpt-4o-mini | + sender in prompt | dev | 214 | 91.1% | 70.3% | 64.0% | 0.666 |
| 5 | gpt-4o-mini | + rewritten definitions | dev | 214 | 91.6% | 72.4% | 66.4% | 0.680 |
| 6 | gpt-4o | same prompt, stronger model | dev | 214 | 90.7% | 85.1% | 77.1% | 0.792 |
| 7 | gpt-4o | final prompt, held-out | test | 266 | 89.1% | 86.9% | 77.4% | 0.814 |
| **8** | **gpt-4o-mini** | **like-for-like against run 7** | **test** | **266** | **92.9%** | **83.0%** | **77.1%** | **0.795** |
| 9 | gpt-4o-mini | repeat of run 8, unchanged | test | 266 | 92.1% | 83.3% | 76.7% | 0.793 |

### Does the stronger model earn its cost? No.

Runs 7 and 8 are the same prompt on the same held-out rows, differing only in
model:

| | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|
| gpt-4o-mini | 92.9% | 83.0% | 77.1% | 0.795 |
| gpt-4o | 89.1% | 86.9% | 77.4% | 0.814 |
| difference | −3.8 | **+3.9** | **+0.3** | +0.019 |

**gpt-4o buys about 4 points of covered accuracy and nothing at all on strict
accuracy**, for roughly 15× the cost per call and a lower rate limit. It also
abstains more often, so mini answers more emails. The project stays on
gpt-4o-mini.

**A correction worth recording.** On dev the same comparison looked like +12.7
points (run 5 vs run 6), and that was reported internally as the model being the
dominant factor. It was not. The same gpt-4o-mini configuration scored 72.4% on
dev and 83.0% on test — a 10.6-point swing between splits, larger than the model
difference itself. The dev gap was mostly split difficulty, not capability. This
is why the like-for-like run on held-out data is the only one quoted.

### What each change was actually worth

| Change | Verdict |
|---|---|
| Sender address added to the prompt | **Nothing.** +0.2 on dev, inside noise. Bodies already carry forwarded headers, so the address was largely redundant. Kept because it is principled and free, but it did not help |
| Category definitions rewritten ("Work is not the default") | **Real and free.** +2.1 on dev, and the effect holds on test: Work precision 42.9% → 81.4% |
| gpt-4o-mini → gpt-4o | **+3.9 covered accuracy, +0.3 strict.** Not worth 15× cost |

Runs 1 → 2 are not a model change: that is the evidence verifier no longer
rejecting correct quotes over typography. Coverage rose 5.8 points because fewer
emails were pushed to Review; accuracy-on-covered fell 1.8 because rows that
were previously abstentions are now answered, some wrongly. Strict accuracy,
which counts every row, rose 3.0.

### Shipped-configuration detail (run 8, test split, gpt-4o-mini)

```
n=266   coverage 92.9%   accuracy 83.0%   strict 77.1%   macro-F1 0.795
```

Per class, over covered rows:

| Class | Precision | Recall | F1 |
|---|---|---|---|
| Work | 81.4% | 75.0% | 0.781 |
| Personal | 80.0% | 58.1% | 0.673 |
| Promotions | 76.9% | 80.6% | 0.787 |
| Studies | 93.8% | 92.4% | 0.931 |

Confusion matrix (rows = true label; from run 9):

| | Work | Personal | Promotions | Studies | Review |
|---|---|---|---|---|---|
| **Work** | 57 | 5 | 8 | 0 | 6 |
| **Personal** | 11 | 36 | 7 | 1 | 7 |
| **Promotions** | 2 | 3 | 50 | 3 | 4 |
| **Studies** | 0 | 1 | 0 | 61 | 4 |

**Broken down — do not quote the pooled figure alone:**

| Group | n | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|---|
| real text (Enron) | 200 | 91.5% | **78.1%** | 71.5% | 0.749 |
| synthetic text (generated) | 66 | 93.9% | 98.4% | 92.4% | 0.961 |
| label_source `human` | 124 | 91.1% | 76.1% | 69.4% | 0.777 |
| label_source `folder_heuristic` | 76 | 92.1% | 81.4% | 75.0% | 0.857 |
| label_source `generation_prompt` | 66 | 93.9% | 98.4% | 92.4% | 0.961 |

Class and source remain correlated — Studies is the only generated class, and
the model identifies it almost perfectly. Part of any pooled number is therefore
the model telling real mail from model-written mail, which is not FR-02.

**If one categorisation figure goes on the slide, use 78.1% on real email.**

---

## Run-to-run variance

Runs 8 and 9 are the **same model, same prompt, same rows, same batch size**,
executed twice:

| | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|
| run 8 | 92.9% | 83.0% | 77.1% | 0.795 |
| run 9 | 92.1% | 83.3% | 76.7% | 0.793 |
| spread | 0.8 | 0.3 | 0.4 | 0.002 |

`temperature=0` is not determinism. Batch composition changes what context each
email is classified alongside, and the provider does not guarantee identical
output for identical input. **Treat anything under about half a point as noise**,
and state the batch size with any figure quoted.

---

## FR-01 — Summarisation groundedness

```bash
python -m eval.evaluate_grounding --task summarise --limit 60
```

Entity backend: **spaCy NER** (`en_core_web_sm`). The figure depends on which
extractor ran, so it is not reproducible without this.

| Run | Change | Attempted | Produced | Groundedness |
|---|---|---|---|---|
| A | before proper-noun fixes | 60 | 57 | 82.5% |
| **B** | **after** | **60** | **57** | **93.0%** |

Run B detail:

```
GROUNDEDNESS RATE  93.0%   (53 clean / 57 produced)
claims checked     222 across 57 outputs (3.9 per output)
outputs with at least one checkable claim: 51 / 57
failed outright    3   (EmptyEmailError — reported separately, not scored)
```

| text_origin / class | n | grounded |
|---|---|---|
| real / Personal | 13 | 84.6% |
| real / Promotions | 14 | 100% |
| real / Work | 15 | 86.7% |
| synthetic / Studies | 15 | 100% |

**Claims-checked is part of the result.** A groundedness rate over outputs
containing no numbers, dates or names is vacuous — it would read 100% however
badly the model behaved. 3.9 checkable claims per summary is what makes 93.0%
mean something.

---

## FR-03 — Draft reply groundedness

```bash
python -m eval.evaluate_grounding --task draft --limit 40
```

| Run | Change | Attempted | Produced | Groundedness |
|---|---|---|---|---|
| A | before salutation fix | 40 | 38 | 78.9% |
| **B** | **after** | **40** | **38** | **97.4%** |

```
GROUNDEDNESS RATE  97.4%   (37 clean / 38 produced)
claims checked     66 across 38 outputs (1.7 per output)
failed outright    2   (EmptyEmailError)
```

Production failures are never counted as grounded. Folding them in would let a
run that mostly failed report a high score on the survivors.

---

## Verifier corrections made during evaluation

Each was found by inspecting flagged output, confirmed as a false positive, and
fixed narrowly. All have regression tests proving genuine fabrications are still
caught.

| Fix | False positive it removed | Effect |
|---|---|---|
| Evidence compared with punctuation stripped | Model appends a full stop to an otherwise verbatim quote | FR-02 coverage 82.5% → 88.3% |
| Proper nouns: strip leading articles and possessives | `Robert Parker's`, `the Trust Agreement` flagged when the bare name is in the source | FR-01 82.5% → 93.0% |
| Proper nouns: strip salutations | spaCy returns `Dear Student Services` as one ORG span (it handles `Hi Sarah` correctly) | FR-03 78.9% → 97.4% |

These raised the measured numbers by making the measurement correct, not by
weakening the check. `Priya Sharma`, `Acme Holdings` and `Dear Acme Holdings`
are all still flagged — see `tests/test_grounding.py`.

---

## Known limitation: the Work labels are wrong

The 120 Work rows are `label_source = folder_heuristic`, meaning only "it was in
the inbox". All 120 were read: **27 (22.5%) are not Work** — 13 Personal, 13
Promotions, 1 Studies.

| Subject | Labelled | Actually |
|---|---|---|
| `250,000 Life Policy $6.50 per month` | Work | Promotions — spam |
| `Adult Industry Secrets Revealed!` | Work | Promotions — spam |
| `HYPERIA NEW YEARS - TONIGHTS THE NIGHT!!!!!!!` | Work | Promotions — club flyer |
| `FFL Playoffs` | Work | Personal — fantasy football |
| `Pelican Schedule` | Work | Personal — sports fixtures |
| `Re: Christmas names` | Work | Personal — Secret Santa |
| `Just a reminder` | Work | Personal — from a spouse |
| `PIRA's API Weekly Comment` | Work | Promotions — subscription bulletin |

This is the same failure already corrected in the Personal class. Corrections
are staged in `eval/data/review_work.csv` awaiting human verification; nothing
has been applied.

**The reported accuracy therefore understates the classifier.** Once the Work
labels are corrected, expect the figure to rise — as a measurement correction,
not a capability improvement, and it must be described as such.

---

## Why not ROUGE

ROUGE scores n-gram overlap against a reference summary. It cannot detect
hallucination: a fluent, wholly fabricated summary that reuses the email's
vocabulary scores well, and that is the failure this project exists to catch.

**It also cannot be computed on this dataset at all.** DR-01 contains labelled
categories, not reference summaries. Reporting ROUGE would first require
hand-writing a reference summary for every email — and the resulting number
still would not answer the hallucination question.

If ROUGE appears in the RTM, that is the work it implies. Groundedness is the
metric that addresses the actual risk.

---

## What a groundedness flag does and does not mean

A flag means a token in the output is not in the source. That is evidence of a
problem, not proof of one — a legitimate paraphrase can flag. Zero flags means
nothing checkable is missing, **not** that the summary is true.

Both directions belong in the limitations section.

---

## Cost and rate limits

- **gpt-4o costs roughly 15× gpt-4o-mini per call** and, measured like for like,
  is worth +3.9 covered accuracy and +0.3 strict. `backend/.env` specifies
  `gpt-4o-mini`; runs 6 and 7 used an environment override.
- **gpt-4o has a lower rate limit.** The first attempt at run 7 died with
  `RateLimitError`. `--delay 8` paces the batches, and `client.py` now waits
  before its single retry, honouring `Retry-After` when the server sends one —
  previously the retry fired 0.23s after the failure, which made the retry
  policy decorative for the one error where it matters most.
