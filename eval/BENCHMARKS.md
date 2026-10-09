# Benchmark runs

Every measured result, in the order it was produced. Numbers are copied from the
runs named beside them: nothing here is estimated.

All runs use `temperature=0`. Categorisation runs 1–10 sent 20 emails in each
model call; runs 11 and 12 send one email per call, which is now the shipped
default (`CLASSIFY_BATCH_SIZE=1`). The voice intent harness has always made one
call per transcript. Batching matters for
[Run-to-run variance](#run-to-run-variance): see that section before quoting
any figure to more than one decimal place.

---

## Headline figures

Measured with the shipped configuration (`gpt-4o-mini`, as set in
`backend/.env`), on data that configuration was not tuned against:

| Requirement | Metric | Result |
|---|---|---|
| **FR-02** categorisation | strict accuracy, Review counted as wrong (test split, n=226) | **89.8%** |
| | over the emails it answered (coverage 99.1%) | 90.6% |
| | on real email only, strict (n=168) | **86.9%** |
| | on a holdout nobody had scored, strict (n=123, run 11 settings) | **87.0%** |
| **FR-01** summarisation | groundedness rate, 55 summaries (run C) | **96.4%** |
| **FR-03** draft reply | groundedness rate, 38 drafts (run C) | **97.4%** |
| **FR-05** voice intent | dispatch accuracy, 60 held-out transcripts, three runs | **91.7–95.0%**: at or above ≥90% on every run; the 95% CIs still reach below it |
| | wrong action dispatched | **0 of 180** attempts |
| **NFR-01** latency | cold inbox load, 25 emails, 8 loads | **median 2.0 s, worst 2.7 s**: all under 5 s |
| **FR-07** translation | numbers, links and addresses preserved, 37 test-split emails each | **89.2%** Spanish, **86.5%** Chinese (Simplified): figures only, not meaning |

The FR-02 figures are **run 13**, measured on the 400-email set, and recompute
from `eval/data/test_preds_run13.csv`; the holdout figure recomputes from
`eval/data/holdout_preds_per_email.csv`. **Strict accuracy is quoted first**
because it is the figure a marker can hold against the 80% target without
asking what happened to the emails the classifier declined: Review counts as a
miss. The figures this table carried before run 11 (83.8%, and 81.5% on real
email) were accuracy over answered emails only. Counted strictly, run 10 was
77.2%, and **73.9% on real email, below the target.** The change that closed the
gap was classifying one email per call: see
[One email per call](#one-email-per-call-runs-11-and-12).

Runs 10–13 are measured against the corrected labels. Runs 1-9 were
measured against the earlier 480-row set, whose Work class was labelled by
folder name and was wrong on 27 of 120 rows. Those runs remain valid history
and the comparisons between them still hold, because each compares like with
like, but they describe a dataset that no longer exists, and their numbers
should not be quoted as current.

**NFR-01 is measured as a cold inbox load**, the slowest request the app makes
routinely: the first `GET /api/inbox` after sign-in, when every email still has
to be classified. Eight loads are not a p95, and the figure excludes the browser
and the mail source; [its section](#nfr-01-cold-inbox-load) has the method and
the settings that were compared.

Categorisation and voice intent are the only accuracies here. Summarisation and
drafting have no single correct output to score against, so they use
groundedness: see [Why not ROUGE](#why-not-rouge).

FR-05 is measured on 60 transcripts written before the fixed prompt was run on
them, plus 22 out-of-scope probes. The original 30 are still reported, but the
fix was tuned on them, so its 100% there is not evidence.
[Its own section](#fr-05-voice-intent-dispatch-accuracy) has both, and why 60
transcripts still cannot establish 90% with confidence.

---

## The dataset these run against

`eval/data/dataset.csv`: 400 rows, balanced 100 per class, which is DR-01's size.

| | rows |
|---|---|
| Work / Personal / Promotions / Studies | 100 each |
| **real** email text | **300** |
| synthetic email text (Studies, the class no real corpus supplies) | 100 |
| `label_source = human` (verified row by row) | 300 |
| `label_source = generation_prompt` | 100 |

Split for tuning: **dev 174 / test 226**, assigned deterministically by hashing
the row id (40% dev). Every prompt and model choice below was made on dev. The
reported figure was measured on test. Runs 10–12 used the 376-row set (94 per
class, dev 161 / test 215) that preceded it; see
[Growing the set to 400](#growing-the-set-to-400-run-13).

**Every label on a real email is now human-verified.** `folder_heuristic` is
gone: the Work class was read row by row and 27 of its 120 rows were not Work
at all (13 Personal, 13 Promotions, 1 a conference invitation from a business
school that is professional correspondence rather than study). Those rows moved
to their true classes, which left Work with 94 and the set was rebalanced to
94 per class rather than topping Work back up with fresh unverified rows.

That is why the figures below differ from earlier runs against the 480-row set.
**It is a measurement correction, not a better classifier**: on most of the
rows that changed, the model had been right and was being marked wrong against
a bad label.

---

## FR-02: Categorisation accuracy

### Why three numbers, not one

`Review` is an abstention, not a wrong answer: the classifier routes an email
there when its quoted evidence fails verification or its confidence is below
threshold. So each run reports:

- **coverage**: share given a real category rather than Review
- **accuracy**: correct, over covered rows only
- **strict**: Review counted as wrong

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
| 10 | gpt-4o-mini | corrected labels, 94/class | test | 215 | 92.1% | 83.8% | 77.2% | 0.802 |
| 11 | gpt-4o-mini | one email per call (`CLASSIFY_BATCH_SIZE=1`) | test | 215 | 97.7% | 92.9% | 90.7% | 0.918 |
| 12 | gpt-4o-mini | + image alt text, HTML fallback, footer rule, spam sentence | test | 215 | 99.5% | 92.1% | 91.6% | 0.917 |
| **13** | **gpt-4o-mini** | **same configuration; the set grown to 400; the quoted run** | **test** | **226** | **99.1%** | **90.6%** | **89.8%** | **0.902** |

Run 8 stays in the table because it happened and because the variance section
below needs both halves of the pair. It is no longer the run quoted, for one
reason only: **its per-row predictions were not retained.** Run 9 is the same
model, prompt, rows and batch size, and it has a committed file behind it.

### Which saved prediction file is which run

| File | Run | Recomputes to (coverage / accuracy / strict / macro-F1) |
|---|---|---|
| `eval/data/predictions.csv` | 2 | 88.3% / 75.5% / 66.7% / 0.701 |
| `eval/data/test_preds.csv` | 7 | 89.1% / 86.9% / 77.4% / 0.814 |
| `eval/data/test_preds_mini.csv` | 10 | 92.1% / 83.8% / 77.2% / 0.802 |
| `eval/data/test_preds_run11_per_email.csv` | 11 | 97.7% / 92.9% / 90.7% / 0.918 |
| `eval/data/test_preds_run12.csv` | 12 | 99.5% / 92.1% / 91.6% / 0.917 |
| `eval/data/test_preds_run13.csv` | **13** | 99.1% / 90.6% / 89.8% / 0.902 |
| `eval/data/holdout_preds_per_email.csv` | holdout, one email per call | 96.7% / 89.9% / 87.0% / 0.894 |
| `eval/data/holdout_preds_batch20.csv` | holdout, 20 per call | 82.9% / 76.5% / 63.4% / 0.733 |
| `eval/data/dev_preds.csv` | none: see below | 82.2% / 78.4% / 64.5% / 0.681 |

Every file but the last reproduces its row exactly, from the committed file,
with no model call:

```bash
python - <<'PY'
import csv
from eval.evaluate_classifier import _score          # the same scoring code the run used
rows = list(csv.DictReader(open("eval/data/test_preds_run13.csv", encoding="utf-8")))
m = _score([(r["expected"], r["predicted"]) for r in rows])
print(f"{m['coverage']:.1%} / {m['accuracy']:.1%} / {m['strict']:.1%} / {m['macro_f1']:.3f}")
PY
# 99.1% / 90.6% / 89.8% / 0.902
```

From run 11 on, every row of `--out` also records the model and the batch
settings that produced it, and `--out` refuses to replace an existing file
without `--force`: the overwrite described next can no longer happen by
accident.

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
is +0.3 against run 8 and +0.7 against run 9: at or barely above the 0.4-point
run-to-run spread on strict documented below, from a pair of runs that changed
nothing at all. gpt-4o also abstains more often, so mini answers more emails.
The project stays on gpt-4o-mini.

**A correction worth recording.** On dev the same comparison looked like +12.7
points (run 5 vs run 6), and that was reported internally as the model being the
dominant factor. It was not. The same gpt-4o-mini configuration scored 72.4% on
dev and 83.3% on test: a 10.9-point swing between splits, larger than the model
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

### One email per call (runs 11 and 12)

Runs 1–10 sent 20 emails in one request. Run 11 changes only that: each email
is its own call (`CLASSIFY_BATCH_SIZE=1`), several at once, with the prompt,
verifier and threshold unchanged. Paired on the same 215 test rows, counting
Review as wrong, with an exact McNemar test (brackets are Wilson 95% intervals):

| | Strict, all (n=215) | Strict, real email (n=161) | Right / misfiled / Review |
|---|---|---|---|
| run 10, 20 per call | 77.2% [71.2, 82.3] | 73.9% [66.6, 80.1] | 166 / 32 / 17 |
| run 11, one per call | 90.7% [86.1, 93.9] | 88.8% [83.0, 92.8] | 195 / 15 / 5 |
| run 12, + the changes below | **91.6%** [87.2, 94.6] | **89.4%** [83.7, 93.3] | 197 / 17 / 1 |

- **Run 10 → 11: +13.5 points strict.** 34 rows only run 11 got right against 5
  only run 10 did (p = 2.4×10⁻⁶); on real email, 28 against 4 (p = 1.9×10⁻⁵).
  Misfiled emails halved along with the abstentions, so this is not Review
  traded for errors. The largest class gain is Personal: 66.7% → 91.7% strict
  (12 rows gained, none lost, p = 0.0005).
- **Run 11 → 12: no measurable change** (3 against 1, p = 0.63). Run 12 adds
  image alt text, an HTML fallback when the plain-text part cleans to nothing,
  a footer rule that no longer cuts a marketing email at its first
  "unsubscribe", and one sentence placing spam and scams in Promotions. They
  exist for real inboxes rather than for this dataset: the preprocessing
  changes alter the cleaned text of 5 of its 376 rows, and on dev the spam
  sentence moved 3 of 161 predictions in both directions (87.6% → 87.0% strict,
  p = 1) where re-running the unchanged prompt moved 1.

Why it helps: a 20-email request asks the model to keep 20 verbatim evidence
quotes and 20 judgements apart in one response. On the holdout below, the
batched run lost 16 emails to evidence that failed verification and 2 that the
response left out altogether; one call per email lost 2, and none.

**Confirmed on data nobody had scored.** More than forty configurations have
been scored on the same 215 test rows, so run 11's change was measured once
more on rows no run had ever seen: `eval/data/holdout_unscored.csv`, the 123
verified rows the 94-per-class cap left out (62 Personal, 35 Promotions, 26
Studies). It has no Work, because every verified Work row is already in the
dataset. Four further Promotions candidates were excluded because their bodies
are byte-identical to dataset rows (one mass mailing delivered to several Enron
mailboxes), so their text is not unseen.

| Holdout, n=123 | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|
| 20 per call | 82.9% | 76.5% | 63.4% | 0.733 |
| one per call | 96.7% | 89.9% | **87.0%** | 0.894 |
| one per call, real email only (n=97) | 95.9% | 87.1% | **83.5%** | 0.877 |

Paired, 30 rows only one-per-call got right against 1 only batching did
(p = 3×10⁻⁸); on real email, 24 against 1 (p = 1.5×10⁻⁶). **The gain replicates,
at the same size, on fresh data.** The holdout is harder than the test split
for both settings and lacks a Work class, so compare its two rows with each
other, not with run 11.

Since then, the 100-per-class merge moved 17 of those 123 rows into the dataset
(6 Personal, 5 Promotions, 6 Studies), so `holdout_unscored.csv` now holds the
other 106. The two prediction files keep all 123, so the table above still
recomputes.

What it costs: the instructions are sent with every email rather than once per
20, so classification rises from US$0.06 to US$0.15 per 1,000 emails at
gpt-4o-mini prices (measured in `eval/data/compare/REPORT.md`), and a cold
inbox load makes one call per email: 25 for a default inbox, all at once, which
is what brought it under 5 seconds ([NFR-01](#nfr-01-cold-inbox-load)). The
per-session request cap still counts one unit per 20 emails, so a cold load
uses the same allowance as before. `CLASSIFY_BATCH_SIZE=20` restores the batched
design; nothing else needs to change with it.

### Growing the set to 400 (run 13)

DR-01 asks for 400 emails, 100 per class. Twelve more Work emails from the mined
Enron pool were read and confirmed by a person (2026-10-08), and the set was
rebuilt with `--merge --per-class 100`. Within a class, rows of equal quality
are kept in id order, so Work (now 106 verified rows) kept its 100 lowest ids:
the 12 new rows came in and 6 earlier ones fell out. The other classes took
their next 6 rows, 17 of them from the holdout. In all, 30 rows were added, 6
removed, and none relabelled. Run 13 is the shipped configuration, unchanged,
on the new test split.

**The classifier did not change; the test rows did.** On the 210 test rows the
two splits share, run 12 scored 91.4% strict and run 13 91.0%: one row apart
(p = 1). The headline fell from 91.6% to 89.8% because the merge took out 5 test
rows run 12 had right, all Work, and brought in 16, of which run 13 gets 12. Two
of the four it misses are new Work mail that reads like Personal: a résumé
("jpk's resume") and a short "Re: Hey". The new rows are harder, not the model
worse, and the 89.8% describes the set DR-01 asks for.

### Shipped-configuration detail (run 13, test split, gpt-4o-mini)

Every table in this section recomputes from `eval/data/test_preds_run13.csv`.

```
n=226   coverage 99.1%   accuracy 90.6%   strict 89.8%   macro-F1 0.902
```

Per class, over covered rows:

| Class | Precision | Recall | F1 |
|---|---|---|---|
| Work | 94.7% | 81.8% | 0.878 |
| Personal | 81.8% | 86.5% | 0.841 |
| Promotions | 88.7% | 94.0% | 0.913 |
| Studies | 96.6% | 98.3% | 0.974 |

Confusion matrix (rows = true label):

| | Work | Personal | Promotions | Studies | Review |
|---|---|---|---|---|---|
| **Work** | 54 | 8 | 4 | 0 | 0 |
| **Personal** | 2 | 45 | 2 | 1 | 2 |
| **Promotions** | 0 | 2 | 47 | 1 | 0 |
| **Studies** | 1 | 0 | 0 | 57 | 0 |

Most of what remains is Work read as Personal (8) or as Promotions (4): Work
precision is the second highest of the four classes and its recall the lowest.
The Work/Personal boundary (recruiting mail, colleagues writing about life
outside work) is where the errors are.

**Broken down (do not quote the pooled figure alone):**

| Group | n | Coverage | Accuracy | Strict | Macro-F1 |
|---|---|---|---|---|---|
| real text (Enron), all `human` labels | 168 | 98.8% | 88.0% | **86.9%** | 0.880 |
| synthetic text (`generation_prompt`) | 58 | 100.0% | 98.3% | 98.3% | 0.991 |

The `label_source` split is no longer a separate table: every real row is now
`human` and every synthetic row is `generation_prompt`, so it carries exactly
the same information as the two rows above.

Class and source remain correlated: Studies is the only generated class, and
the model identifies it far more easily than the rest. Part of any pooled
number is therefore the model telling real mail from model-written mail, which
is not FR-02.

**If one categorisation figure goes on the slide, use 86.9% strict on real
email**: Review counted as a miss, synthetic Studies mail left out. It comes
from the same file as everything else in this section, so it is reproducible
on the same command. If a second figure fits, it is the holdout's 83.5% strict
on real email: lower, and the stronger evidence, because no configuration was
ever scored on those rows before.

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
intent for all 30 transcripts every time**: 0.0 points of spread, against 0.3–0.8
for the batched classifier. One confidence *score* still drifted (0.95 → 0.90),
so the provider is not bit-identical even unbatched; it is batching that turns
that into movement in the headline. This supports batch composition as the
dominant variance source rather than sampling.

One email per call bears that out for the classifier itself. Run 11 and the
model comparison's unbatched gpt-4o-mini run (`eval/data/compare/`) are separate
executions a day apart, through different harnesses (the backend's own
`classify_emails` and the comparison's adapter), and they agree on **all 215
predictions**. Two dev runs of one configuration (161 rows) disagreed on 1 row
and scored 87.6% strict both times. The half-point rule above was written for
batched runs; unbatched, the spread is a row or two.

The provider can still drift between dates: the shipped intent prompt, re-run
on its 30 transcripts on 2026-10-06, scored 86.7% again but split its errors 2
wrong dispatches and 2 declines, where the 2026-09-29 runs had 1 and 3.

### `dev_preds.csv` is an incomplete run, not a run with odd numbers

It reconciles with no entry in the history table, and the reason is that its
three figures are not a measurement of anything. **18 of its 214 rows carry no
model label at all.** They are recorded as `Review` with `confidence` exactly
0.0, which is what `classify_emails` backfills when the model's batch response
omits an id it was asked about (`REASON_MISSING_FROM_RESPONSE` in
`backend/orchestrator/classify.py`), and what `--out` then writes for them.

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
rows depress **coverage** (82.2%, against 90.7–92.1% for every recorded dev run)
while leaving **accuracy** arithmetically untouched, because accuracy is
computed over covered rows only. Accuracy is nonetheless flattered, because 17
of the rows that vanished are Work, the hardest class. Over the 196 rows that
were actually classified the file reads **89.8% coverage / 78.4% accuracy /
70.4% strict / 0.714 macro-F1**.

**Which configuration produced it cannot be established.** Those corrected
figures match no recorded dev run, and could not be compared with one anyway:
the recorded runs cover all 214 rows and this one covers 196, missing 17 of the
hardest. The only hint is Work precision at 51.9%, well below the 81.4% the
rewritten category definitions bought on test, which points at a prompt from
before that change: run 3 or run 4. But the dropout biases precision downward
too, so that is a hint, not an identification.

The file is kept rather than deleted for two reasons: `eval/notebook.ipynb`
reads it, and the failure mode is worth having on the record. **A run can
silently lose rows and still report three plausible-looking figures**: this one
reads as a merely disappointing run rather than a broken one, and only the
confidence column gives it away. No published figure depends on it and nothing
in this document quotes it.

---

## FR-01: Summarisation groundedness

```bash
python -m eval.evaluate_grounding --task summarise --limit 60
```

Entity backend: **spaCy NER** (`en_core_web_sm`). The figure depends on which
extractor ran, so it is not reproducible without this.

| Run | Change | Attempted | Produced | Groundedness |
|---|---|---|---|---|
| A | before proper-noun fixes | 60 | 57 | 82.5% |
| B | after | 60 | 57 | 93.0% |
| **C** | **re-run 2026-10-09: the 400-email set, today's preprocessing and date rule** | **60** | **55** | **96.4%** |

Run C detail (`eval/data/grounding_summarise.csv`, which now records
`claims_checked` per output):

```
GROUNDEDNESS RATE  96.4%   (53 clean / 55 produced)
claims checked     197 across 55 outputs (3.6 per output)
outputs with at least one checkable claim: 48 / 55
failed outright    5   (EmptyEmailError: reported separately, not scored)
```

| text_origin / class | n | grounded |
|---|---|---|
| real / Personal | 13 | 92.3% |
| real / Promotions | 14 | 100% |
| real / Work | 13 | 92.3% |
| synthetic / Studies | 15 | 100% |

The two flags left are both names: "Call Crystal" and "the NYISO Market
Orientation Course", the same two that run B flagged on the same emails.

**Run C is not evidence of a better summariser.** The sample is the first 15
rows of each class in file order, so it is mostly the same emails: 54 of the
55 summarised are emails run B also summarised. Two outputs run B flagged
("January 17th" on an ISAS meeting agenda, "the AOL Local Guide for Kingwood
Cove Golf Course") are clean in run C. Today's checker still flags both claims
as run B worded them, so the model simply did not write them this time; the
check did not get looser. Two outputs in 55 is 3.6 points, and that is the
whole difference between B and C. Quote 96.4% with its n, and treat the two
runs as agreeing.

The two extra failures are Work rows the 400-email merge brought into the
first 15: a "Thanks" above a quoted message, and a forward whose only content
is an attached image. Both clean to nothing by design, so there is nothing to
summarise. Cleaning makes no model call, so the same five fail on every run.

**Claims-checked is part of the result.** A groundedness rate over outputs
containing no numbers, dates or names is vacuous: it would read 100% however
badly the model behaved. 3.6 checkable claims per summary is what makes 96.4%
mean something.

---

## FR-03: Draft reply groundedness

```bash
python -m eval.evaluate_grounding --task draft --limit 40
```

| Run | Change | Attempted | Produced | Groundedness |
|---|---|---|---|---|
| A | before salutation fix | 40 | 38 | 78.9% |
| B | after | 40 | 38 | 97.4% |
| **C** | **re-run 2026-10-09: the 400-email set, today's preprocessing and date rule** | **40** | **38** | **97.4%** |

Run C detail (`eval/data/grounding_draft.csv`):

```
GROUNDEDNESS RATE  97.4%   (37 clean / 38 produced)
claims checked     69 across 38 outputs (1.8 per output)
outputs with at least one checkable claim: 30 / 38
failed outright    2   (EmptyEmailError)
```

37 of the 38 drafted emails are ones run B drafted, and the one flag is the
same as run B's: "the NYISO Market Orientation Course", on the same email.

Production failures are never counted as grounded. Folding them in would let a
run that mostly failed report a high score on the survivors.

---

## FR-05: Voice intent dispatch accuracy

```bash
python -m eval.intent_harness                  # the original 30 + 8, 38 model calls
python -m eval.intent_harness --baseline-only  # dataset difficulty, 0 calls
python -m eval.intent_harness --graded eval/data/voice_intents_heldout.csv \
    --probes eval/data/voice_intents_heldout_unknown.csv   # held-out 60 + 22
```

Two measurements, two prompts. The shipped prompt was measured on the original
30 on **2026-09-29**, and the sections down to
[the prompt fix](#the-prompt-fix-measured-on-transcripts-it-was-not-tuned-on)
are that measurement. The prompt was then fixed and measured on 60 new
transcripts on **2026-10-06**; that is the current figure. `gpt-4o-mini`,
`temperature=0`, one call per transcript throughout. A figure depends on the
model *and* on `INTENT_SYSTEM` in `backend/orchestrator/prompts.py`, so the
harness prints the prompt's hash with every run: `899a1ccdab1b` is the prompt
measured in 2026-09, `c9fd6e5fbcba` the one shipped now. Every 2026-10-06 run,
transcript by transcript, is in `eval/data/voice_intent_runs/`.

### How `unknown` is scored: read this before quoting the number

`unknown` is a required outcome, not a failure mode: spec 6.3 has the interface
show the transcript back and ask. So it is scored in the two places it appears,
differently, and on purpose:

- **The graded 30** (`voice_intents.csv`) are all genuine commands: every
  expected label is `summarise`, `read` or `draft`. The criterion is "dispatched
  to the correct action", and declining to dispatch is not dispatching, so an
  `unknown` here **counts as a miss**.
- **The 8 out-of-scope probes** (`voice_intents_unknown.csv`) are commands the
  app does not implement. There `unknown` is the **only** correct answer and is
  scored as a success.

The acceptance figure is the first of these. **86.7% is the number for the
criterion.** The safety figure below (96.7%) is a different quantity and is not
a substitute for it.

### Result on the original 30, shipped prompt: the criterion was not met

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
for, which is the figure a user would feel: on this set it declined three times
and acted wrongly once. Neither replaces the other, and 96.7% is **not** a pass
against a criterion written about dispatch.

| Run | Harness | Accuracy | Wrong dispatch | Declined | Probes |
|---|---|---|---|---|---|
| 1 | as committed | 86.7% | 1 | 3 | 8/8 |
| 2 | as committed, repeat | 86.7% | 1 | 3 | 8/8 |
| **3** | **+ reporting added (below)** | **86.7%** | **1** | **3** | **8/8** |
| 4 | shipped prompt again, 2026-10-06 | 86.7% | 2 | 2 | 8/8 |
| 5 | fixed prompt: tuned on these 30, so not evidence | 100% | 0 | 0 | 8/8 |

Runs 1–3, the same 26 transcripts right and the same 4 wrong each time. One
confidence score moved between runs 1 and 2 (0.95 → 0.90 on *can you summarize
the latest email*); no dispatched intent changed. The batch-composition variance
documented for FR-02 does not apply here (each transcript is its own call with
no neighbours), so this figure is more stable than the categorisation ones, and
**the spread is 0.0 points across three runs.**

### Per intent

| Intent | Support | Times chosen | Precision | Recall | F1 |
|---|---|---|---|---|---|
| summarise | 10 | 10 | 90.0% | 90.0% | 0.900 |
| **read** | 10 | 7 | **100.0%** | **70.0%** | **0.824** |
| draft | 10 | 10 | 100.0% | 100.0% | 1.000 |
| `unknown` | 0 | 3 | 0.0% | - | - |

Macro-F1 over the three graded intents: **0.908**.

**`read` is the weak intent, and it fails in the safe direction.** Its precision
is 100% (nothing was ever wrongly dispatched *to* `read`), while its recall is
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
"the summary".** The app's own flow produces exactly these utterances (you
summarise an email, then ask for the summary to be read out), so the transcripts
are realistic, and the prompt is what is underspecified. `INTENT_SYSTEM` defines
`read` as "the user wants an email read out loud" and `summarise` as "the user
wants an email summarised". Neither covers *read the summary out loud*, which
contains both an existing summary and a request to speak it. The model then does
the defensible thing under an ambiguous spec: it abstains twice and picks the
other reading once. Only the `play the summary` row is a wrong dispatch, and it
is the one where the model was most confident (0.90): **the single most
expensive error in the set is also the one it was surest about**, which is worth
saying plainly, because it means confidence is not usable as a guard here.

The fourth, *whats the enrolment email about*, is an indirect request with no
summarise verb in it. It is phrased as a question, and the model declined.

A prompt fix was the obvious next step: `read` needed to cover reading out a
summary, and `summarise` the question form. It has since been made, and
because it was written after reading these four failures, these 30 can no
longer test it: run 5's 100% is a fit, not a measurement. **86.7% stands as the
figure for the prompt measured here**, and the fixed prompt is measured on new
transcripts [below](#the-prompt-fix-measured-on-transcripts-it-was-not-tuned-on).

### Is n=30 enough to support the claim? No.

At n=30 one transcript is worth 3.3 points, and 90% of 30 means "at most three
errors". The measured result is four. The 95% CI on 86.7% is
**[70.3%, 94.7%], which contains 90%**, so this run does not establish that the
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
[the synthetic rows in DR-01](#fr-02-categorisation-accuracy): check what the
data actually contains before believing what it produces.

Run `--baseline-only`. **A three-line keyword regex scores 28/30 = 93.3% on the
graded set: it passes the criterion the model fails.**

| | Graded 30 | Out-of-scope 8 | Wrong dispatches, both sets |
|---|---|---|---|
| `gpt-4o-mini` | 86.7% | **100%** | **1** |
| keyword regex | **93.3%** | 87.5% | 2 |

The regex was written after reading the transcripts, so it is not a fair rival
classifier: it is an **upper bound on how far this set can be solved by
spotting a verb**, and that bound being this high is the problem. Concretely:

- **26 of 30 transcripts contain exactly one intent keyword, matching their own
  label.** The model gets **26/26 = 100%** of those.
- The other 4 are cue-free or carry two competing cues. The model gets
  **0/4 = 0%** of those.

So the headline is a weighted average of a 100% subset and a 0% subset, with the
26:4 weighting chosen by whoever wrote the CSV, not by any measurement of how
users actually speak. **Change that ratio and the headline moves anywhere between
0% and 100% without the classifier changing at all.** 86.7% is therefore not an
estimate of field performance; it is an estimate of performance on this mix.

The regex also shows why the keyword route was not taken: its extra 6.6 points
are bought with `mark this as unread` → `read`, because "unread" contains
"read". That is a wrong dispatch on an out-of-scope command (the costly error
class), and the model got it right. **The regex wins the headline and loses the
failure mode that matters.**

Other properties of the set, for the record: 30 distinct transcripts, exactly 10
per intent (real usage is not balanced), 4–10 words each (median 7), no
punctuation and no capitals (correct: that is what the Web Speech API returns),
3 with filler words, 24 opening with a bare imperative verb, 20 naming a target
and 10 anaphoric. The surface form is right: these do look like Web Speech
output. **The vocabulary is too cooperative**: 26 of 30 name their action with
the obvious verb and nothing else, exactly one names no action verb at all, and
the remaining three name two. Every error the classifier made is in that last
group of four.

**What this figure does and does not support.** It supports "on 30 written
transcripts, the shipped prompt dispatched 26 correctly and misdispatched one".
It does not support "the voice feature is 86.7% accurate", and it cannot be
compared to the FR-02 figures, which were measured on held-out data the prompt
was never tuned against. To claim a dispatch rate at all, the set needs to be
larger and to be collected rather than composed: transcripts from people who
were not told which three intents exist, including the indirect phrasings and
summary-then-read utterances the app's own flow produces.

### The prompt fix, measured on transcripts it was not tuned on

**The order mattered, so here it is.** Sixty new graded transcripts (20 per
intent, `eval/data/voice_intents_heldout.csv`) and 22 new out-of-scope probes
(`voice_intents_heldout_unknown.csv`) were written first. The shipped prompt
was measured on them. Only then was the prompt changed (tuned on the original
30), and the changed prompt measured on the 60. The file timestamps in
`eval/data/voice_intent_runs/` show that sequence.

What the fix says (`INTENT_SYSTEM`, hash `c9fd6e5fbcba`): `read` means the user
wants to *hear* it, which in this app is always the summary read aloud, so
"read me the summary" and "play the summary" are `read`; `summarise` covers
questions about an email ("what's the email from Emma about"); decide by what
the user wants to happen, not by which words appear; anything else is
`unknown`.

| Prompt | Run | Correct, n=60 | 95% CI | Wrong dispatch | Declined | Probes → `unknown` |
|---|---|---|---|---|---|---|
| shipped before (`899a1ccdab1b`) | 1 | 46 = 76.7% | [64.6, 85.6] | 3 | 11 | 22/22 |
| shipped before | 2 | 48 = 80.0% | [68.2, 88.2] | 3 | 9 | 22/22 |
| **fixed (`c9fd6e5fbcba`)** | 1 | **57 = 95.0%** | [86.3, 98.3] | **0** | 3 | 22/22 |
| fixed | 2 | 55 = 91.7% | [81.9, 96.4] | 0 | 5 | 22/22 |
| fixed | 3 | 56 = 93.3% | [84.1, 97.4] | 0 | 4 | 22/22 |

- **The fix meets the criterion on every run and never acted wrongly**: 0 wrong
  dispatches in 180 attempts, against 3 per run before. `read` and `summarise`
  went to 20/20 each on run 1.
- **What it still misses is short or indirect commands.** "let tom know i can
  make it on friday", "say yes to the dinner invite from mum" and "reply
  please" on every run; the bare "summarise it" on runs 2 and 3; "help me get
  back to the recruiter" on run 2. Every one is a decline at confidence 0.5 or
  below, never a wrong action, and a decline shows the transcript back and
  asks.
- **This set is much harder than the original.** The keyword regex that scored
  93.3% on the original 30 scores 33/60 = 55.0% here, with 7 wrong dispatches.
  The old prompt's 76.7–80.0% on it is the fairer picture of what it would have
  done with indirect speech.

What it still does not establish:

- **n=60 is still not enough to show 90% with confidence.** Every run's 95%
  interval reaches below 90%; the lowest lower bound is 81.9%. The point
  estimate meets the criterion three times out of three; the interval does not
  rule out a system that would not.
- **The transcripts were composed, not collected.** They were written by the
  same person who then wrote the fix, after the failure analysis above was
  known, before the fix was run on them, but not blind to what it would
  target. Transcripts from people who were never told the three intents remain
  the test this set cannot replace.
- **Typed commands are not FR-05.** The command bar sends typed text through
  the same classifier. Typed text has no recognition errors, so nothing
  measured on it can stand in for the spoken criterion.

---

## NFR-01: Cold inbox load

```bash
python -m eval.cold_load --settings 1x25,1x16,1x8 --out eval/data/nfr01/<new>.json
```

Target: under 5 seconds (the Week 6 deck). Measured on the slowest request the
app makes routinely: the first `GET /api/inbox` after sign-in, with nothing
cached, so every email in the inbox is classified inside that one request. The
reload straight after it took 74–114 ms on every trial and is not the
constraint.

Method: the real Flask app and route through Flask's test client, the real
model (`gpt-4o-mini`), a 25-email fixture mailbox (25 is `GMAIL_LIMIT`'s
default) drawn from the test split, 6–7 per class. Cache and session budget are
cleared before every trial, and the settings are interleaved trial by trial so
drift in the provider's latency falls on all of them alike. Measured 2026-10-07
from one laptop on a home connection; every trial is in `eval/data/nfr01/`.

| Settings | Loads | Median | Range | Under 5 s |
|---|---|---|---|---|
| 20 emails per call (the design before run 11) | 3 | 13.5 s | 11.3–14.9 s | 0/3 |
| one per call, 8 at once | 9 | 5.1 s | 4.7–29.3 s | 3/9 |
| one per call, 16 at once | 8 | 3.1 s | 2.9–5.2 s | 7/8 |
| **one per call, 25 at once (shipped)** | **8** | **2.0 s** | **1.7–2.7 s** | **8/8** |

`CLASSIFY_CONCURRENCY` decides it: 25 matches the default inbox, so the whole
inbox is one wave of calls of about a second each. The default was 8 when one
call per email first shipped, which measured a median of 5.1 s and stayed under
the target on 3 of 9 loads; it is now 25.

- **The 29.3 s load is not a concurrency effect.** All eight calls in flight
  failed with a connection error at 19.2 s and were retried once, successfully:
  it is the tail any setting has when the provider stalls, and
  `OPENAI_TIMEOUT_SECONDS=20` sets its size.
- **The first load after the server starts is slower**: 4.2 s at 25 at once,
  about 9 s at 8, because it also opens the connections later loads reuse. It
  is reported apart and left out of the table.
- **What is not measured**: the browser, the network between browser and
  server, and the mail source. A fixture directory stands in for Gmail, whose
  fetch adds its own time before classification starts.
- **Eight loads are not a p95.** `GET /api/metrics` reports the p95 the spec
  asks for over the last 100 requests, and a session's requests are mostly
  cached reloads, so that figure will sit far below these. The cold load is
  quoted instead because it is the request a user waits for.

---

## FR-07: Translation (figures preserved)

```bash
python -m eval.evaluate_translation --language Spanish --limit 40 --out eval/data/translation/<new>.csv
python -m eval.evaluate_translation --language "Chinese (Simplified)" --limit 40 --out eval/data/translation/<new>.csv
```

The RTM gives FR-07 no acceptance figure, and there are no reference
translations to score fluency against. What can be checked in any language
pair is the error that does real damage: a figure changed on the way through
(an amount that lost a zero, a date read the other way round, a link one
character off). So every number, link and email address in the original must
appear in the translation, and nothing of the kind may appear that the original
lacks. Numbers compare by their digits, so `1,000.50` and `1.000,50` match.
`gpt-4o-mini`, temperature 0, 2026-10-08, the first 10 test-split emails of
each class; 3 of the 40 have nothing left to translate once cleaned (a 422 in
the app) and are reported apart. Every run, email by email, is in
`eval/data/translation/` (ids, counts and flags; never text).

| Run | Spanish | Chinese (Simplified) |
|---|---|---|
| 1, strict check | 89.2% (33/37) | 54.1% (20/37) |
| 1, re-scored with the month exception (below) | 89.2% | 83.8% (31/37) |
| **2, as shipped** | **89.2% (33/37)** | **86.5% (32/37)** |

- **What was checked:** 189 numbers, 6 links and 7 email addresses; 28 of the
  37 originals contain at least one, so the other 9 pass with nothing to check.
- **What the run-2 flags are:** figures written differently from the original, such as
  `1,000` for `1`, `1999` for `99`, `02` for `2`, numbers written out in Chinese
  characters. None is a figure invented from nothing.
- **Long text:** a body is translated in pieces of at most 2,500 characters at
  once, to stay inside the client's 20-second timeout. Live through the route,
  9,498 characters in four pieces took 9.3 s into Chinese and 6.0 s into
  Spanish, with no flags.
- **What this is not:** a quality score. A fluent mistranslation that keeps
  every figure passes, only 2 of the 15 languages were measured, and comparing
  digits alone means `1.5` and `15` look the same.

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
| Dates, weekdays and two-digit years compared by meaning | `July 14` flagged against an email's `14JUL`, `Thursday` against `Thurs`, `January 17th` against `Jan 17th` | Same 55 summaries, both verifiers: gpt-4o-mini 90.9% → 94.5%, gemini-3.8-flash 87.3% → 90.9%, no flag added |
| Translation: a month named in the original may return as its number | `October 15` → `10月15日` flagged as an invented `10` (how Chinese, Japanese and Korean write dates) | FR-07 Chinese 54.1% → 83.8% on the same 37 translations; Spanish unchanged. The reverse, a numeric date written out with a month name, is still flagged |

These raised the measured numbers by making the measurement correct, not by
weakening the check. `Priya Sharma`, `Acme Holdings` and `Dear Acme Holdings`
are all still flagged: see `tests/test_grounding.py`. So are a different day
of the same month, a different month and a different weekday
(`tests/test_grounding_dates.py`).

The first version of the date rule let some things through that only look
like dates, and a review caught them before release: "24/7", "1/2 of the
total", "3-5 business days" and "Mon-Fri 9-5" were read as numeric dates;
"Step 2 may take" as 2 May; "Your SAT registration" and "The Sun reported" as
weekdays; and 6'10" as the year 2010. Each now flags again, and each has a test.
A numeric date in the source now needs its year, so a bare "14/7" no longer
supports "July 14": a false flag on a real date, which is the cheaper mistake.
None of the four flags in the table's measurement depended on what was
narrowed, so its figures stand. They were measured on summaries generated for
the model comparison. FR-01 and FR-03 were re-run with the date rule in place
(run C of each, 2026-10-09).

### Reporting added to the intent harness: no measured value changed

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

## Corrected before run 10: the Work labels were wrong

*History. Runs 1–9 were measured against these labels; runs 10–12 are not.*

The 120 Work rows were `label_source = folder_heuristic`, meaning only "it was
in the inbox". All 120 were read: **27 (22.5%) were not Work** (13 Personal, 13
Promotions, 1 Studies).

| Subject | Labelled | Actually |
|---|---|---|
| `250,000 Life Policy $6.50 per month` | Work | Promotions: spam |
| `Adult Industry Secrets Revealed!` | Work | Promotions: spam |
| `HYPERIA NEW YEARS - TONIGHTS THE NIGHT!!!!!!!` | Work | Promotions: club flyer |
| `FFL Playoffs` | Work | Personal: fantasy football |
| `Pelican Schedule` | Work | Personal: sports fixtures |
| `Re: Christmas names` | Work | Personal: Secret Santa |
| `Just a reminder` | Work | Personal: from a spouse |
| `PIRA's API Weekly Comment` | Work | Promotions: subscription bulletin |

This was the same failure already corrected in the Personal class. The
corrections in `eval/data/review_work.csv` were verified row by row and applied,
the rows moved to their true classes, and the set was rebalanced to 94 per class
([the dataset](#the-dataset-these-run-against)). Runs 1–9 understate the
classifier for this reason. The rise at run 10 is a measurement correction, not
a capability improvement, and is described as one.

---

## Why not ROUGE

ROUGE scores n-gram overlap against a reference summary. It cannot detect
hallucination: a fluent, wholly fabricated summary that reuses the email's
vocabulary scores well, and that is the failure this project exists to catch.

**It also cannot be computed on this dataset at all.** DR-01 contains labelled
categories, not reference summaries. Reporting ROUGE would first require
hand-writing a reference summary for every email, and the resulting number
still would not answer the hallucination question.

If ROUGE appears in the RTM, that is the work it implies. Groundedness is the
metric that addresses the actual risk.

---

## What a groundedness flag does and does not mean

A flag means a token in the output is not in the source. That is evidence of a
problem, not proof of one: a legitimate paraphrase can flag. Zero flags means
nothing checkable is missing, **not** that the summary is true.

Both directions belong in the limitations section.

---

## Cost and rate limits

- **gpt-4o costs roughly 15× gpt-4o-mini per call** and, measured like for like,
  is worth +3.9 covered accuracy and +0.3 strict. `backend/.env` specifies
  `gpt-4o-mini`; runs 6 and 7 used an environment override.
- **gpt-4o has a lower rate limit.** The first attempt at run 7 died with
  `RateLimitError`. `--delay 8` paces the batches, and `client.py` now waits
  before its single retry, honouring `Retry-After` when the server sends one:
  previously the retry fired 0.23s after the failure, which made the retry
  policy decorative for the one error where it matters most.
- **One email per call costs 2.5× as much to classify**: US$0.15 per 1,000
  emails against US$0.06, because the instructions travel with every email
  (833 input tokens per email against 226; `eval/data/compare/REPORT.md`). On
  that report's assumed usage profile (700 emails classified a week, with
  summaries, drafts and voice commands), a user-week rises from about US$0.066
  to about US$0.13, which still fits about 38 users inside the US$5/week budget.
- **25 calls in flight reach a rate limit sooner** than one batched call did. A
  call that hits one waits and retries once; if it happens routinely, lower
  `CLASSIFY_CONCURRENCY`, at the latency cost [measured above](#nfr-01-cold-inbox-load).
  No run here hit one: runs 11 and 12 and every cold load completed without a
  rate-limit retry.
