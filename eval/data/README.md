# Evaluation dataset (DR-01, DR-02)

Rebuild everything with:

```bash
python -m eval.build_dataset --enron --huggingface --merge --per-category 120
```

## Schema

Every row in every CSV carries the same ten columns:

| Column | Values | Meaning |
|---|---|---|
| `id` | `<provenance>-<sha1[:12]>` | Stable row identity |
| `provenance` | `enron` \| `huggingface` \| `generated` | Which corpus the text came from |
| `text_origin` | `real` \| `synthetic` | **Is this genuine human-written mail, or templated/generated text?** |
| `label_source` | `folder_heuristic` \| `dataset_label` \| `generation_prompt` \| `human` | **Who decided the label** |
| `label_confidence` | `weak` \| `strong` | How much the label can be trusted |
| `category` | `Work` \| `Personal` \| `Promotions` \| `Studies` | The label |
| `subject`, `body`, `sender`, `received_at` | text | Parsed from headers, quoted history stripped |
| `source_ref` | text | Path or row reference back to the source corpus |

`provenance` and `label_source` are deliberately **separate columns**. They answer
different questions and the trade-off between them is the whole story:

- A **generated** email has a perfect label (we told the model which class to
  write) but is not real mail.
- An **Enron** email is unquestionably real but its label is inferred.

Collapsing these into one "is it fake" flag would hide exactly the thing a
reader of the report needs to see. Always report accuracy **broken down by
`provenance` and `label_source`**, never as a single pooled number.

## Sources

| Provenance | Source | Licence | Status |
|---|---|---|---|
| `enron` | [CMU Enron corpus](https://www.cs.cmu.edu/~enron/), 517k messages | Public, research use | **Built** — 240 rows |
| `huggingface` | [jason23322/high-accuracy-email-classifier](https://huggingface.co/datasets/jason23322/high-accuracy-email-classifier) | Apache-2.0 | **Built** — 120 rows (Promotions only) |
| `generated` | Produced by the project's own orchestrator | n/a | **Built** — 120 rows (Studies only) |

Current merged set: **480 rows across all four classes**, 120 per class:

| provenance | text_origin | category | rows |
|---|---|---|---|
| `enron` | real | Work | 120 |
| `enron` | real | Personal | 120 |
| `huggingface` | synthetic | Promotions | 120 |
| `generated` | synthetic | Studies | 120 |

**240 real / 240 synthetic.** Report accuracy split on `text_origin`, never pooled.

Raw archives live in `raw/` and are gitignored (the Enron tarball is 443 MB).
The curated CSVs are committed.

## What the Enron corpus actually provides

Scanning the folder distribution across 28 users:

```
12121  all_documents        7196  inbox
 8737  deleted_items        6516  discussion_threads
 7212  sent_items           4327  sent
```

These are **organisational folders, not categories**. Enron is a corporate
mailbox, so the overwhelming majority of it is Work. It contains essentially
**zero Promotions and zero Studies**.

The Week 11 deck states Enron supplies "Work / Personal categories". That is
optimistic: it reliably supplies Work, and its Personal signal is poor.

### The folder heuristic is measurably unreliable

Of the 120 rows this builder labelled `Personal` from `personal` /
`personalfolder` folders, **86 (72%) were sent from `@enron.com` corporate
addresses**, with subjects including:

```
Your May 31 Pay Advice
2001 Special Stock Option Grant Awards
FW: NERC 10 Year Assessment - Early Draft
EES Remote Offices
```

Those are Work emails that a user happened to file in a folder called
"personal". Only a minority ("Superbowl Party", "thanks!") are genuinely
personal correspondence.

**Consequence: these labels must not be used as DR-02 ground truth as they
stand.** An accuracy figure computed against them would mostly measure the
noise in the folder names, and would understate the classifier — it would be
penalised for correctly calling a payroll notice "Work".

### What to do instead

Three defensible options, best first:

1. **Hand-label a sample.** 200–400 rows across three people is a few hours and
   turns `label_source` into `human` / `label_confidence` into `strong`. This is
   the only route to a citable accuracy number on real mail.
2. **Use Enron unlabelled**, for summarisation and grounding evaluation, where
   no category label is needed and its authenticity is the point.
3. **Use the HuggingFace labels** as the classification ground truth for
   Promotions, with Enron as qualitative real-mail evidence. Note the trade-off
   below: those labels are trustworthy but the text is synthetic.


## The HuggingFace corpus is synthetic, not real mail

The Week 11 deck cites this source under *"Real emails. Not AI testing AI."*
The data does not support that. Measured over all 13,477 rows:

| Signal | Finding |
|---|---|
| Placeholder domains | 15% of rows contain `example.com` |
| Obvious fixtures | Bodies contain `bit.ly/fakeprize` and a literal `phishing-site` |
| Subject reuse | 13,477 rows share only 2,910 distinct subjects |
| Body length | Median 87 characters |
| Templating bug | One template emits `"Complete within 48hrshrs"` |

It is templated text. That is why every row from it carries
`text_origin = synthetic`. The distinction is not academic: if this corpus is
described as real email in the report, the "not AI testing AI" claim is wrong,
because a synthetic corpus is being used to grade a model.

Its labels are still good — they are consistent and the source asserts them
directly, so `label_source = dataset_label` and `label_confidence = strong`.
Synthetic text with a trustworthy label is the mirror image of Enron: real text
with an untrustworthy one.

### Only one of its six classes was imported

Its taxonomy is `forum`, `promotions`, `social_media`, `spam`, `updates`,
`verify_code` — six classes that are not the project's four. Only `promotions`
maps cleanly, so only `promotions` was taken (2,245 available, capped at 120 to
keep the merged set balanced).

The other five were skipped rather than force-fitted. `spam` is not
`Promotions`; `updates` and `verify_code` are transactional mail that could sit
in Work or Personal depending on context. An invented mapping would surface as
classifier error that is really annotator error.

The value is real regardless: Enron supplies **no** Promotions, and this fills
that class.

## Unresolved: the DR-01 strategy

Two project documents disagree, and they imply different datasets:

- **The RTM (Week 11, slide 6)** — DR-01 is *"AI-generated test dataset of 400
  emails (100 per category)"*.
- **The dataset slide (Week 11, slide 12)** — *"Real emails. Not AI testing AI."*
  Enron + HuggingFace, with AI generation used only for *"Studies/Academic only —
  not in either real dataset — fills a gap, not the test."*

The evidence above supports the **slide**: real corpora genuinely do not cover
Studies, so generating that class fills a real hole, whereas generating all 400
would mean evaluating the model largely against text produced by the same model
family.

### Resolved: the slide's strategy was adopted

Generation fills **Studies only** — the one class no real corpus covers. The
other three come from real or third-party data.

The generator draws from 24 scenarios x 8 sender roles x 6 tones with a fixed
seed (`20260826`), so the set is reproducible and does not template. Held to
the same standard the HuggingFace corpus failed:

| Measure | Generated (this set) | HuggingFace |
|---|---|---|
| Distinct subjects | **120 / 120** | 2,910 / 13,477 |
| Distinct subject shapes | **120** | 1,785 |
| Median body length | **567 chars** | 87 chars |

`build_dataset.py` prints these figures on every run and warns if subject reuse
exceeds 10%, so templating would be caught here rather than by a marker.

**Budget note.** A first run stopped at 77 rows on `BudgetExceeded` — the
per-session request cap in `backend/.env` (`MAX_REQUESTS_PER_SESSION`, default
100) working as designed. The full run used a raised cap for the one-off build:

```bash
MAX_REQUESTS_PER_SESSION=400 python -m eval.build_dataset --generate --per-category 120
```
