# Benchmark runs

Every measured result, in the order it was produced. Numbers here are copied
from the runs recorded in this file's commands — nothing is estimated.

**Reproduce any row:** the command is given with it. All runs use
`temperature=0` and `--batch-size 20`.

---

## Headline figures

| Requirement | Metric | Result |
|---|---|---|
| **FR-02** categorisation | accuracy (held-out test) | **86.9%** |
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
reported figure was measured once on test.

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
| 6 | **gpt-4o** | same prompt, stronger model | dev | 214 | 90.7% | 85.1% | 77.1% | 0.792 |
| **7** | **gpt-4o** | **final, held-out** | **test** | **266** | **89.1%** | **86.9%** | **77.4%** | **0.814** |

What each change was worth:

| Change | Effect on dev accuracy |
|---|---|
| Sender address added to the prompt | **+0.2 pts — no effect.** Bodies already carry forwarded headers, so the address was largely redundant |
| Category definitions rewritten ("Work is not the default") | **+2.1 pts.** Work precision 42.9% → 52.5% |
| gpt-4o-mini → gpt-4o | **+12.7 pts.** The dominant factor by a wide margin |

Run 1 → 2 is not a model change: it is the evidence verifier no longer
rejecting correct quotes over typography. Coverage rose 5.8 points because
fewer emails were pushed to Review; accuracy-on-covered fell 1.8 because rows
that were previously abstentions are now answered, some wrongly. Strict
accuracy, which counts every row, rose 3.0.

### Final run detail (run 7, test split, gpt-4o)

```
n=266   coverage 89.1%   accuracy 86.9%   strict 77.4%   macro-F1 0.814
```

Per class, over covered rows:

| Class | Precision | Recall | F1 |
|---|---|---|---|
| Work | 89.5% | 67.1% | 0.767 |
| Personal | 78.4% | 64.5% | 0.708 |
| Promotions | 79.0% | 79.0% | 0.790 |
| Studies | 98.5% | 100.0% | 0.992 |

Confusion matrix (rows = true label):

| | Work | Personal | Promotions | Studies | Review |
|---|---|---|---|---|---|
| **Work** | 51 | 7 | 8 | 0 | 10 |
| **Personal** | 6 | 40 | 5 | 0 | 11 |
| **Promotions** | 0 | 4 | 49 | 1 | 8 |
| **Studies** | 0 | 0 | 0 | 66 | 0 |

**Broken down — do not quote the pooled figure alone:**

| Group | n | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|---|
| real text (Enron) | 200 | 85.5% | **81.9%** | 70.0% | 0.755 |
| synthetic text (generated) | 66 | 100% | 100% | 100% | 1.000 |
| label_source `human` | 124 | 84.7% | **84.8%** | 71.8% | 0.800 |
| label_source `folder_heuristic` | 76 | 86.8% | **77.3%** | 67.1% | 0.803 |
| label_source `generation_prompt` | 66 | 100% | 100% | 100% | 1.000 |

Class and source are still correlated — Studies is the only generated class, and
the model identifies it perfectly. Part of any pooled number is therefore the
model telling real mail from model-written mail, which is not FR-02.

**If one categorisation figure goes on the slide, use 81.9% on real email.**

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
the inbox". Inspecting the 12 dev rows where the classifier disagreed with the
label, **the classifier was right on all 12**:

| Subject | Labelled | Classifier said | Which is right |
|---|---|---|---|
| `250,000 Life Policy $6.50 per month` | Work | Promotions | classifier — it is spam |
| `HYPERIA NEW YEARS - TONIGHTS THE NIGHT!!!!!` | Work | Promotions | classifier — club night flyer |
| `FFL Playoffs` | Work | Personal | classifier — fantasy football |
| `Pelican Schedule` | Work | Personal | classifier — sports fixtures |
| `RE: RE: Whats up!!!!!` | Work | Personal | classifier — Super Bowl chat |

This is the same failure already corrected in the Personal class. It shows in
the results: human-labelled classes score **84.8%**, the folder-heuristic class
**77.3%**.

**The reported accuracy therefore understates the classifier.** Hand-labelling
the Work class — as was done for Personal and Promotions — is expected to
recover roughly 5–8 points. That is a measurement correction, not a capability
improvement, and should be described as such.

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

## Cost and reproducibility notes

- **gpt-4o costs roughly 15× gpt-4o-mini per call.** `backend/.env` still
  specifies `gpt-4o-mini`; run 6 and 7 used an environment override. Adopting
  gpt-4o as the default is a budget decision.
- **gpt-4o has a lower rate limit.** The first test run failed with
  `RateLimitError`. `--delay 8` paces the batches; `client.py` now waits before
  its retry, honouring `Retry-After` when the server sends one.
- **Batch composition affects results.** At temperature 0 the same email in a
  different batch can receive a different evidence span and flip its
  verification outcome. Fix and state the batch size when quoting a figure.
