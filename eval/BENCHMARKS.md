# Benchmark runs

Every measured result, in the order it was produced. Numbers are copied from the
runs named beside them — nothing here is estimated.

All runs use `temperature=0`. The categorisation and grounding runs use
`--batch-size 20`; the voice intent harness is unbatched, one call per
transcript, which matters for
[Run-to-run variance](#run-to-run-variance). See that section before quoting
any figure to more than one decimal place.

---

## Headline figures

Measured on the **held-out test split** with the shipped configuration
(`gpt-4o-mini`, as set in `backend/.env`):

| Requirement | Metric | Result |
|---|---|---|
| **FR-02** categorisation | accuracy (test split, n=215) | **83.8%** |
| | — on real email only | **81.5%** |
| **FR-01** summarisation | groundedness rate | **93.0%** |
| **FR-03** draft reply | groundedness rate | **97.4%** |
| **FR-05** voice intent | dispatch accuracy (n=30) | **86.7%** — criterion ≥90% **not met** |
| | — wrong action dispatched | **3.3%** (1/30) |
| NFR-01 latency | p95 | instrumented, not yet measured |

Both FR-02 figures are **run 10**, and both recompute from
`eval/data/test_preds_mini.csv`, the saved per-row predictions for that run.

Run 10 is the first measurement against the corrected labels. Runs 1-9 were
measured against the earlier 480-row set, whose Work class was labelled by
folder name and was wrong on 27 of 120 rows. Those runs remain valid history
and the comparisons between them still hold, because each compares like with
like — but they describe a dataset that no longer exists, and their numbers
should not be quoted as current.

**NFR-01 is instrumented but unmeasured.** `GET /api/metrics`
(`backend/routes/metrics.py`) reports p95 over the last 100 requests, so the
figure is now collectable; it has simply not been collected against the real
model, and this table will not carry a latency number until it has been. A
single cold-load observation — 8218 ms against the 5000 ms target — exists from
one live run and is discussed under item 10 of `FIXES.md`. One observation is
not a p95 and is not quoted as one here.

Categorisation and voice intent are the only accuracies here. Summarisation and
drafting have no single correct output to score against, so they use
groundedness — see [Why not ROUGE](#why-not-rouge).

FR-05 is measured on a 30-transcript acceptance set, not a held-out split:
there was no tuning pass to hold anything out from. It is the weakest evidence
in this document and [its own section](#fr-05--voice-intent-dispatch-accuracy)
says why.

---

## The dataset these run against

`eval/data/dataset.csv` — 376 rows, balanced 94 per class.

| | rows |
|---|---|
| Work / Personal / Promotions / Studies | 94 each |
| **real** email text | **282** |
| synthetic email text | 94 |
| `label_source = human` (verified row by row) | 282 |
| `label_source = generation_prompt` | 94 |

Split for tuning: **dev 161 / test 215**, assigned deterministically by hashing
the row id (40% dev). Every prompt and model choice below was made on dev. The
reported figure was measured on test.

**Every label on a real email is now human-verified.** `folder_heuristic` is
gone: the Work class was read row by row and 27 of its 120 rows were not Work
at all (13 Personal, 13 Promotions, 1 a conference invitation from a business
school that is professional correspondence rather than study). Those rows moved
to their true classes, which left Work with 94 and the set was rebalanced to
94 per class rather than topping Work back up with fresh unverified rows.

That is why the figures below differ from earlier runs against the 480-row set.
**It is a measurement correction, not a better classifier** — on most of the
rows that changed, the model had been right and was being marked wrong against
a bad label.

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
| 8 | gpt-4o-mini | like-for-like against run 7 | test | 266 | 92.9% | 83.0% | 77.1% | 0.795 |
| 9 | gpt-4o-mini | repeat of run 8, unchanged | test | 266 | 92.1% | 83.3% | 76.7% | 0.793 |
| **10** | **gpt-4o-mini** | **corrected labels, 94/class — the quoted run** | **test** | **215** | **92.1%** | **83.8%** | **77.2%** | **0.802** |

Run 8 stays in the table because it happened and because the variance section
below needs both halves of the pair. It is no longer the run quoted, for one
reason only: **its per-row predictions were not retained.** Run 9 is the same
model, prompt, rows and batch size, and it has a committed file behind it.

### Which saved prediction file is which run

| File | Run | Recomputes to (coverage / accuracy / strict / macro-F1) |
|---|---|---|
| `eval/data/predictions.csv` | 2 | 88.3% / 75.5% / 66.7% / 0.701 |
| `eval/data/test_preds.csv` | 7 | 89.1% / 86.9% / 77.4% / 0.814 |
| `eval/data/test_preds_mini.csv` | **10** | 92.1% / 83.8% / 77.2% / 0.802 |
| `eval/data/dev_preds.csv` | none — see below | 82.2% / 78.4% / 64.5% / 0.681 |

Each of the first three reproduces its row in the history table exactly, from
the committed file, with no model call:

```bash
python - <<'PY'
import csv
from eval.evaluate_classifier import _score          # the same scoring code the run used
rows = list(csv.DictReader(open("eval/data/test_preds_mini.csv", encoding="utf-8")))
m = _score([(r["expected"], r["predicted"]) for r in rows])
print(f"{m['coverage']:.1%} / {m['accuracy']:.1%} / {m['strict']:.1%} / {m['macro_f1']:.3f}")
PY
# 92.1% / 83.8% / 77.2% / 0.802
```

Runs 1, 3, 4, 5, 6, 8 and 9 have no saved predictions of their own: run 9's
file was overwritten by run 10, which reused the same path. Runs 1 and 3-6 are
tuning history and nothing reported rests on them. Nothing reported rests on
runs 8 and 9 either now that run 10 supersedes them, but the overwrite is worth
noting -- `--out` takes whatever path it is given, and a run that reuses a path
destroys the evidence for the previous one.

### Does the stronger model earn its cost? No.

Runs 7 and 8 are the same prompt on the same held-out rows, differing only in
model:

| | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|
| gpt-4o-mini, run 8 | 92.9% | 83.0% | 77.1% | 0.795 |
| gpt-4o-mini, run 9 | 92.1% | 83.3% | 76.7% | 0.793 |
| gpt-4o, run 7 | 89.1% | 86.9% | 77.4% | 0.814 |
| difference, gpt-4o − run 8 | −3.8 | **+3.9** | **+0.3** | +0.019 |
| difference, gpt-4o − run 9 | −3.0 | **+3.6** | **+0.7** | +0.021 |

Both mini runs are shown because run 8 was the pairing originally designed
against run 7, and run 9 is the one that can be recomputed. The verdict does not
depend on which is used.

**gpt-4o buys between three and four points of covered accuracy and under a
point of strict accuracy**, for roughly 15× the cost per call and a lower rate
limit. Strict accuracy is the figure that counts every row, and the gain there
is +0.3 against run 8 and +0.7 against run 9 — at or barely above the 0.4-point
run-to-run spread on strict documented below, from a pair of runs that changed
nothing at all. gpt-4o also abstains more often, so mini answers more emails.
The project stays on gpt-4o-mini.

**A correction worth recording.** On dev the same comparison looked like +12.7
points (run 5 vs run 6), and that was reported internally as the model being the
dominant factor. It was not. The same gpt-4o-mini configuration scored 72.4% on
dev and 83.3% on test — a 10.9-point swing between splits, larger than the model
difference itself. The dev gap was mostly split difficulty, not capability. This
is why the like-for-like run on held-out data is the only one quoted.

### What each change was actually worth

| Change | Verdict |
|---|---|
| Sender address added to the prompt | **Nothing.** +0.2 on dev, inside noise. Bodies already carry forwarded headers, so the address was largely redundant. Kept because it is principled and free, but it did not help |
| Category definitions rewritten ("Work is not the default") | **Real and free.** +2.1 on dev, and the effect holds on test: Work precision 42.9% → 81.4% |
| gpt-4o-mini → gpt-4o | **+3.6 to +3.9 covered accuracy, +0.3 to +0.7 strict** (against runs 9 and 8 respectively). Not worth 15× cost |

Runs 1 → 2 are not a model change: that is the evidence verifier no longer
rejecting correct quotes over typography. Coverage rose 5.8 points because fewer
emails were pushed to Review; accuracy-on-covered fell 1.8 because rows that
were previously abstentions are now answered, some wrongly. Strict accuracy,
which counts every row, rose 3.0.

### Shipped-configuration detail (run 10, test split, gpt-4o-mini)

Run 10 is the first measurement against the corrected labels. Every table in
this section — the headline line, the per-class figures, the confusion matrix
and the breakdown — recomputes from `eval/data/test_preds_mini.csv`.

```
n=215   coverage 92.1%   accuracy 83.8%   strict 77.2%   macro-F1 0.802
```

Per class, over covered rows:

| Class | Precision | Recall | F1 |
|---|---|---|---|
| Work | 80.3% | 75.4% | 0.778 |
| Personal | 82.1% | 66.7% | 0.736 |
| Promotions | 80.9% | 79.2% | 0.800 |
| Studies | 92.2% | 87.0% | 0.895 |

Confusion matrix (rows = true label):

| | Work | Personal | Promotions | Studies | Review |
|---|---|---|---|---|---|
| **Work** | 49 | 3 | 5 | 0 | 8 |
| **Personal** | 6 | 32 | 4 | 1 | 5 |
| **Promotions** | 4 | 1 | 38 | 3 | 2 |
| **Studies** | 2 | 3 | 0 | 47 | 2 |

**Broken down — do not quote the pooled figure alone:**

| Group | n | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|---|
| real text (Enron), all `human` labels | 161 | 90.7% | **81.5%** | 73.9% | 0.784 |
| synthetic text (`generation_prompt`) | 54 | 96.3% | 90.4% | 87.0% | 0.931 |

The `label_source` split is no longer a separate table: every real row is now
`human` and every synthetic row is `generation_prompt`, so it carries exactly
the same information as the two rows above.

Class and source remain correlated — Studies is the only generated class, and
the model identifies it far more easily than the rest. Part of any pooled
number is therefore the model telling real mail from model-written mail, which
is not FR-02.

**If one categorisation figure goes on the slide, use 81.5% on real email.** It
comes from the same file as everything else in this section, so it is
reproducible on the same command.

---

## Run-to-run variance

Runs 8 and 9 are the **same model, same prompt, same rows, same batch size**,
executed twice:

| | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|
| run 8 | 92.9% | 83.0% | 77.1% | 0.795 |
| run 9 | 92.1% | 83.3% | 76.7% | 0.793 |
| spread | 0.8 | 0.3 | 0.4 | 0.002 |

Both were measured on the earlier 480-row set. The pair is kept because it is
the cleanest evidence of the noise floor: same model, same prompt, same rows,
same batch size, run twice.

`temperature=0` is not determinism. Batch composition changes what context each
email is classified alongside, and the provider does not guarantee identical
output for identical input. **Treat anything under about half a point as noise**,
and state the batch size with any figure quoted.

The voice intent harness is the control case for that explanation. It sends one
transcript per call with no batch, and across three runs it returned **the same
intent for all 30 transcripts every time** — 0.0 points of spread, against 0.3–0.8
for the batched classifier. One confidence *score* still drifted (0.95 → 0.90),
so the provider is not bit-identical even unbatched; it is batching that turns
that into movement in the headline. This supports batch composition as the
dominant variance source rather than sampling.

### `dev_preds.csv` is an incomplete run, not a run with odd numbers

It reconciles with no entry in the history table, and the reason is that its
three figures are not a measurement of anything. **18 of its 214 rows carry no
model label at all.** They are recorded as `Review` with `confidence` exactly
0.0, which is what `classify_emails` backfills when the model's batch response
omits an id it was asked about — `REASON_MISSING_FROM_RESPONSE` in
`backend/orchestrator/classify.py` — and what `--out` then writes for them.

Seventeen of the eighteen are one contiguous block: the last 17 rows of a single
20-row batch (rows 180–199 of the dev split), and that batch is entirely Work.
The eighteenth is a lone row in an earlier batch.

The rows are not at fault, and three checks say so. All eighteen have bodies
between 200 and 2818 characters, so none was empty. None of them is among the
three zero-confidence rows in `predictions.csv`, so it is not a property of the
rows that recurs across runs. And run 2 gave fifteen of the same eighteen a real
category, eleven of them at confidence 0.9. The ids were dropped by one
response; they were not declined by the classifier.

That explains the direction of the mismatch precisely. The 18 phantom `Review`
rows depress **coverage** — 82.2%, against 90.7–92.1% for every recorded dev run
— while leaving **accuracy** arithmetically untouched, because accuracy is
computed over covered rows only. Accuracy is nonetheless flattered, because 17
of the rows that vanished are Work, the hardest class. Over the 196 rows that
were actually classified the file reads **89.8% coverage / 78.4% accuracy /
70.4% strict / 0.714 macro-F1**.

**Which configuration produced it cannot be established.** Those corrected
figures match no recorded dev run, and could not be compared with one anyway:
the recorded runs cover all 214 rows and this one covers 196, missing 17 of the
hardest. The only hint is Work precision at 51.9%, well below the 81.4% the
rewritten category definitions bought on test, which points at a prompt from
before that change — run 3 or run 4. But the dropout biases precision downward
too, so that is a hint, not an identification.

The file is kept rather than deleted for two reasons: `eval/notebook.ipynb`
reads it, and the failure mode is worth having on the record. **A run can
silently lose rows and still report three plausible-looking figures** — this one
reads as a merely disappointing run rather than a broken one, and only the
confidence column gives it away. No published figure depends on it and nothing
in this document quotes it.

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

## FR-05 — Voice intent dispatch accuracy

```bash
python -m eval.intent_harness                  # the graded run, 38 model calls
python -m eval.intent_harness --baseline-only  # dataset difficulty, 0 calls
```

Measured **2026-09-29**, `gpt-4o-mini`, `temperature=0`, unbatched. The figure
depends on the model *and* on `INTENT_SYSTEM` in
`backend/orchestrator/prompts.py`; it is not reproducible without both. The
harness exits non-zero below the threshold, so it currently exits 1.

### How `unknown` is scored — read this before quoting the number

`unknown` is a required outcome, not a failure mode: spec 6.3 has the interface
show the transcript back and ask. So it is scored in the two places it appears,
differently, and on purpose:

- **The graded 30** (`voice_intents.csv`) are all genuine commands — every
  expected label is `summarise`, `read` or `draft`. The criterion is "dispatched
  to the correct action", and declining to dispatch is not dispatching, so an
  `unknown` here **counts as a miss**.
- **The 8 out-of-scope probes** (`voice_intents_unknown.csv`) are commands the
  app does not implement. There `unknown` is the **only** correct answer and is
  scored as a success.

The acceptance figure is the first of these. **86.7% is the number for the
criterion.** The safety figure below (96.7%) is a different quantity and is not
a substitute for it.

### Result — the criterion is not met

```
n=30   accuracy 86.7%   (26/30)   95% CI [70.3%, 94.7%]
       threshold 90%  ->  FAIL

wrong dispatch (acted on the wrong intent)   1/30 =  3.3%
declined to guess (returned unknown)         3/30 = 10.0%

never dispatched a wrong action             29/30 = 96.7%   95% CI [83.3%, 99.4%]
out-of-scope probes: 8/8 = 100% returned unknown
```

**Quote both numbers.** 86.7% is the criterion and it is not met. 96.7% is the
share of transcripts on which the app did not do something the user did not ask
for, which is the figure a user would feel — on this set it declined three times
and acted wrongly once. Neither replaces the other, and 96.7% is **not** a pass
against a criterion written about dispatch.

| Run | Harness | Accuracy | Wrong dispatch | Declined | Probes |
|---|---|---|---|---|---|
| 1 | as committed | 86.7% | 1 | 3 | 8/8 |
| 2 | as committed, repeat | 86.7% | 1 | 3 | 8/8 |
| **3** | **+ reporting added (below)** | **86.7%** | **1** | **3** | **8/8** |

Three runs, the same 26 transcripts right and the same 4 wrong each time. One
confidence score moved between runs 1 and 2 (0.95 → 0.90 on *can you summarize
the latest email*); no dispatched intent changed. The batch-composition variance
documented for FR-02 does not apply here — each transcript is its own call with
no neighbours — so this figure is more stable than the categorisation ones, and
**the spread is 0.0 points across three runs.**

### Per intent

| Intent | Support | Times chosen | Precision | Recall | F1 |
|---|---|---|---|---|---|
| summarise | 10 | 10 | 90.0% | 90.0% | 0.900 |
| **read** | 10 | 7 | **100.0%** | **70.0%** | **0.824** |
| draft | 10 | 10 | 100.0% | 100.0% | 1.000 |
| `unknown` | 0 | 3 | 0.0% | — | — |

Macro-F1 over the three graded intents: **0.908**.

**`read` is the weak intent, and it fails in the safe direction.** Its precision
is 100% — nothing was ever wrongly dispatched *to* `read` — while its recall is
70%: three genuine read commands were not recognised as such. The classifier is
not confusing read with something else so much as failing to commit to it.
Recall of 7/10 carries a 95% CI of [39.7%, 89.2%], which is almost the whole
range; **10 transcripts per intent cannot support a per-intent claim at all**,
and the per-intent rows above should be read as a pointer to where to look, not
as measurements.

Confusion matrix (rows = true label):

| | summarise | read | draft | unknown |
|---|---|---|---|---|
| **summarise** | 9 | 0 | 0 | 1 |
| **read** | 1 | 7 | 0 | 2 |
| **draft** | 0 | 0 | 10 | 0 |
| **unknown** (probes) | 0 | 0 | 0 | 8 |

### The four errors are one root cause, not four

| Transcript | Expected | Got | Conf |
|---|---|---|---|
| read aloud the summary of the latest email | read | `unknown` | 0.70 |
| play the summary for the github alert | read | **summarise** | 0.90 |
| say the summary out loud | read | `unknown` | 0.50 |
| whats the enrolment email about | summarise | `unknown` | 0.70 |

**Three of the four are the same collision: a `read` command whose object is
"the summary".** The app's own flow produces exactly these utterances — you
summarise an email, then ask for the summary to be read out — so the transcripts
are realistic, and the prompt is what is underspecified. `INTENT_SYSTEM` defines
`read` as "the user wants an email read out loud" and `summarise` as "the user
wants an email summarised". Neither covers *read the summary out loud*, which
contains both an existing summary and a request to speak it. The model then does
the defensible thing under an ambiguous spec: it abstains twice and picks the
other reading once. Only the `play the summary` row is a wrong dispatch, and it
is the one where the model was most confident (0.90) — **the single most
expensive error in the set is also the one it was surest about**, which is worth
saying plainly, because it means confidence is not usable as a guard here.

The fourth, *whats the enrolment email about*, is an indirect request with no
summarise verb in it. It is phrased as a question, and the model declined.

A prompt fix is the obvious next step — `read` needs to cover reading out a
summary, and `summarise` needs to cover the question form. That is a change to
`backend/orchestrator/prompts.py`, which this evaluation does not own and has
not touched. **Any re-measurement after that change is a new run in the table
above, and the 86.7% stands as the figure for the shipped prompt.**

### Is n=30 enough to support the claim? No.

At n=30 one transcript is worth 3.3 points, and 90% of 30 means "at most three
errors". The measured result is four. The 95% CI on 86.7% is
**[70.3%, 94.7%] — which contains 90%**, so this run does not establish that the
classifier is below the criterion either. It establishes that 30 samples cannot
tell.

That is a property of the acceptance criterion, not of this run:

| If the true dispatch rate were… | P(a fresh 30-transcript run reports PASS) |
|---|---|
| exactly 90% (meets spec) | **64.7%** |
| 95% | 93.9% |
| 86.7% (as measured) | 41.9% |

**A system that exactly meets the requirement fails this test roughly a third of
the time.** The criterion as written in the spec is under-powered by
construction, and "30 spoken commands, ≥90%" cannot distinguish a 90% system
from an 80% one. Reporting 86.7% without this table would overstate what was
learned in either direction.

### The transcript set is easier than real speech

This is the finding worth more than the number, and it is the same lesson as
[the synthetic rows in DR-01](#fr-02--categorisation-accuracy): check what the
data actually contains before believing what it produces.

Run `--baseline-only`. **A three-line keyword regex scores 28/30 = 93.3% on the
graded set — it passes the criterion the model fails.**

| | Graded 30 | Out-of-scope 8 | Wrong dispatches, both sets |
|---|---|---|---|
| `gpt-4o-mini` | 86.7% | **100%** | **1** |
| keyword regex | **93.3%** | 87.5% | 2 |

The regex was written after reading the transcripts, so it is not a fair rival
classifier — it is an **upper bound on how far this set can be solved by
spotting a verb**, and that bound being this high is the problem. Concretely:

- **26 of 30 transcripts contain exactly one intent keyword, matching their own
  label.** The model gets **26/26 = 100%** of those.
- The other 4 are cue-free or carry two competing cues. The model gets
  **0/4 = 0%** of those.

So the headline is a weighted average of a 100% subset and a 0% subset, with the
26:4 weighting chosen by whoever wrote the CSV — not by any measurement of how
users actually speak. **Change that ratio and the headline moves anywhere between
0% and 100% without the classifier changing at all.** 86.7% is therefore not an
estimate of field performance; it is an estimate of performance on this mix.

The regex also shows why the keyword route was not taken: its extra 6.6 points
are bought with `mark this as unread` → `read`, because "unread" contains
"read". That is a wrong dispatch on an out-of-scope command — the costly error
class — and the model got it right. **The regex wins the headline and loses the
failure mode that matters.**

Other properties of the set, for the record: 30 distinct transcripts, exactly 10
per intent (real usage is not balanced), 4–10 words each (median 7), no
punctuation and no capitals (correct — that is what the Web Speech API returns),
3 with filler words, 24 opening with a bare imperative verb, 20 naming a target
and 10 anaphoric. The surface form is right — these do look like Web Speech
output. **The vocabulary is too cooperative**: 26 of 30 name their action with
the obvious verb and nothing else, exactly one names no action verb at all, and
the remaining three name two. Every error the classifier made is in that last
group of four.

**What this figure does and does not support.** It supports "on 30 written
transcripts, the shipped prompt dispatched 26 correctly and misdispatched one".
It does not support "the voice feature is 86.7% accurate", and it cannot be
compared to the FR-02 figures, which were measured on held-out data the prompt
was never tuned against. To claim a dispatch rate at all, the set needs to be
larger and to be collected rather than composed — transcripts from people who
were not told which three intents exist, including the indirect phrasings and
summary-then-read utterances the app's own flow produces.

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

### Reporting added to the intent harness — no measured value changed

`eval/intent_harness.py` was extended while running FR-05, and that is a change
to a measuring instrument, so it is recorded here rather than left in a commit
message. **Nothing about what is scored was touched**: the accuracy definition,
the 0.90 threshold, the CSVs and the exit code are all as they were, which is why
runs 1–3 in the FR-05 table agree exactly. What was added is reporting the run
was already entitled to:

| Added | Why |
|---|---|
| Wrong dispatches counted apart from `unknown` | The original lumped both into "misclassified". They cost a user completely different things |
| Per-intent precision / recall / F1, macro-F1 | Derived from the confusion counts the harness already had. This is what identified `read` as the weak intent |
| Wilson 95% CI on every rate | A bare percentage at n=30 implies precision the sample cannot carry |
| `--baseline-only`: keyword baseline, 0 API calls | Makes the "a regex scores 93.3%" finding checkable without a key or any spend |

The pass/fail gate was deliberately **not** loosened to count `unknown` as
correct on the graded set. Doing so would have reported 96.7% and a PASS, by
redefining the criterion rather than meeting it.

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
