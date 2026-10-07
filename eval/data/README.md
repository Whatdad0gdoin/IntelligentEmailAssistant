# Evaluation dataset (DR-01, DR-02)

Rebuild the merged dataset from the curated sources with:

```bash
python -m eval.build_dataset --merge --per-class 100
```

That reproduces the committed `dataset.csv` exactly (`tests/test_build_dataset.py`
checks it). Raise `--per-class` only after verifying more rows for the short
class: `merge` now refuses to write an unbalanced set, and says which
`--per-class` would be balanced.

**Do not re-run `--enron` casually.** Until 2026-10-06 it let a freshly sampled
folder-guess row win an id collision with a human-verified row, and because the
sampler walks the archive in a fixed order it re-collects exactly the emails
people already read: the documented command would have replaced all 120
human-reviewed Work rows and reverted 26 human relabels. Human rows now always
win, but a rebuild still adds nothing new — it samples the same 12 mailboxes.

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
| `enron` | [CMU Enron corpus](https://www.cs.cmu.edu/~enron/), 517k messages | Public, research use | **Built** - `real_enron.csv`, 395 human-verified rows: Personal 156, Promotions 133, Work 106 |
| `generated` | Produced by the project's own orchestrator | n/a | **Built** - 120 rows (Studies only) |
| `huggingface` | [jason23322/high-accuracy-email-classifier](https://huggingface.co/datasets/jason23322/high-accuracy-email-classifier) | Apache-2.0 | **No longer used** - replaced by real Enron Promotions; see the analysis below for why |

Current merged set: **400 rows, all four classes, 100 per class** — DR-01's
size:

| provenance | text_origin | category | label_source | rows |
|---|---|---|---|---|
| `enron` | real | Work | `human` | 100 |
| `enron` | real | Personal | `human` | 100 |
| `enron` | real | Promotions | `human` | 100 |
| `generated` | synthetic | Studies | `generation_prompt` | 100 |

**300 real / 100 synthetic.** Report accuracy split on `text_origin`, never
pooled: `eval/BENCHMARKS.md` run 13, the shipped configuration, records 86.9%
strict on real email against 98.3% on synthetic (Review counted as a miss), so
a pooled figure is partly the model telling real mail from model-written mail,
which is not what FR-02 asks.

The set reached 400 on 2026-10-08, when twelve more Work emails from the mined
pool were read and confirmed (`review_work_new.csv`). Rows of equal quality are
kept in id order, so Work kept its 100 lowest ids out of 106 verified rows, and
six earlier Work rows now sit in `real_enron.csv` outside the set.

**`holdout_unscored.csv` — 106 verified rows outside the set.** It began as the
123 verified rows the 94-per-class cut left out, minus four Promotions rows whose
bodies are byte-identical to dataset rows (one mass mailing delivered to several
mailboxes). It was scored once in each mode to confirm the switch to one email
per call (`BENCHMARKS.md`, "Confirmed on data nobody had scored"). The
100-per-class merge then took 17 of them into the set, which leaves 56
Personal, 30 Promotions and 20 Studies, no Work, and no overlap with
`dataset.csv` by id or by body. Keep it for confirming changes chosen on the
test split; any future merge at a higher `--per-class` draws on the same rows,
which must then be dropped from it again.

> **Class and `text_origin` are perfectly confounded.** Studies is the only
> generated class and the only one no real corpus supplies. Any comparison
> between Studies and the rest is therefore also a comparison between synthetic
> and real text, and neither effect can be separated from the other on this
> set. State that wherever a per-class figure is quoted.

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

### RESOLVED: the Personal class was dropped from Enron

The folder heuristic worked for Work and failed for Personal. All 120 rows it
had labelled `Personal` were read by hand. The tally, judged from subject lines:

| True class | Count | Examples |
|---|---|---|
| **Work** | ~77 | `Your May 31 Pay Advice`, `2001 Special Stock Option Grant Awards`, `RE: Unforced capacity credits`, `Organizational Announcement` |
| **Personal** | ~27 | `Superbowl Party`, `Baby Shower for the Little Transter`, `FW: Wedding photos`, `saturday get together` |
| **Promotions** | ~11 | `Your Digital ID is about to expire` (x4), `Your ImageStation Order` (x3), `EREN Network News` |
| unclear | ~5 | subjects that are only `RE:` or `FW:` |

**The label was right about one time in four**, and the errors were not all in
one direction -- the bucket was contaminated by two other classes at once.

An earlier version of this file reported "86 of 120 (72%) sent from corporate
addresses" and used that as the measure. Sender domain turned out to be the
wrong proxy in both directions: `saturday get together` and `RE: hellooo` came
*from* `@enron.com` (colleagues arranging social things), while several
external-domain rows (`ImageStation Order`, `Digital ID`) are automated
transactional mail and not personal at all. Reading the subjects is the sounder
measure, and it is less flattering than the domain count.

**Action taken.** `ENRON_FOLDER_LABELS` no longer maps any folder to Personal,
and the 120 rows were removed from `real_enron.csv`. At that point Enron
contributed Work only, which is the one class its folders supply reliably. (It
now supplies Personal and Promotions too, from the hand-reviewed candidates
below.)

Real personal correspondence *is* in the corpus -- roughly 20-25 usable rows
per 120 sampled -- but at a density the folder names cannot find. Recovering it
needs hand labelling, not a better folder map.

### Filling Personal: done (rows reviewed and applied)

Option 1 was taken. The full Enron archive was pulled and scanned with
`extract_personal_candidates.py`, which selects on **structural** signals only
-- consumer mail domain, few recipients, no bulk sender, shallow forward chain.
Deliberately not keyword signals: selecting Personal rows by the words that
make an email obviously personal would produce a class of easy cases and
flatter the classifier. Plenty of survivors are Work (recruiters on Yahoo,
vendors on AOL), which is the property a keyword filter would destroy.

486 candidates were then read with their bodies and given proposed categories
(`proposed_labels.json`): **Personal 174, Work 146, Promotions 146, Studies 6**,
14 unusable.

**These proposals came from a language model and are NOT ground truth.** They
are staged in `review_personal.csv` (143 rows) and `review_promotions.csv`
(120 rows) as `model_proposed`, and `--apply` refuses to run until a person has
confirmed or corrected every row. Model labels used to grade a model are not an
evaluation: the two share failure modes, so the emails that confuse the
classifier are disproportionately the ones that confused the labeller, and
measured accuracy comes out too high.

```bash
python -m eval.label_candidates --build  --category Personal
# fill in the `verified` column, then
python -m eval.label_candidates --apply  --category Personal
python -m eval.build_dataset --merge --per-class 100   # always pass --per-class
```

Both review files are now fully verified and applied: `review_personal.csv`
143/143 and `review_promotions.csv` 120/120. The later Work review
(`review_work.csv`, 120/120) moved 27 rows out of Work, which left the set at
94 per class until twelve more Work emails were verified
(`review_work_new.csv`, 12/12).

#### Selection bias, which must be in the report

This is not a random sample. The Personal class it yields is a defined
subpopulation: *personal mail arriving at a corporate inbox, usually from an
outside consumer address.* Personal mail between two colleagues on internal
addresses is systematically under-represented, because the domain signal cannot
see it. Random sampling at ~5% Personal density would have meant hand-labelling
~2,400 messages to reach 120; this is the trade that was made instead.

### Promotions can become real too

The same scan turned up **146 genuine 2001-02 marketing and spam messages** --
airline fare alerts, credit card offers, loan and pharmaceutical spam, job
board newsletters, industry price bulletins. 120 are staged in
`review_promotions.csv`.

**This has since been done.** The synthetic HuggingFace class was replaced by
these real messages, moving the merged set from 120 real / 240 synthetic to
360 real / 120 synthetic (282 real / 94 synthetic after the Work relabel, and
300 / 100 once twelve more Work emails were verified). The
Week 11 deck's "Real emails. Not AI testing
AI." claim is now defensible for three of the four classes, with Studies the
only generated one -- the position the slide actually argued for.

Promotions had no rejection margin: it landed on exactly 120.


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

Its labels are still good - they are consistent and the source asserts them
directly, so `label_source = dataset_label` and `label_confidence = strong`.
Synthetic text with a trustworthy label is the mirror image of Enron: real text
with an untrustworthy one.

### Only one of its six classes was imported

Its taxonomy is `forum`, `promotions`, `social_media`, `spam`, `updates`,
`verify_code` - six classes that are not the project's four. Only `promotions`
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

- **The RTM (Week 11, slide 6)** - DR-01 is *"AI-generated test dataset of 400
  emails (100 per category)"*.
- **The dataset slide (Week 11, slide 12)** - *"Real emails. Not AI testing AI."*
  Enron + HuggingFace, with AI generation used only for *"Studies/Academic only -
  not in either real dataset - fills a gap, not the test."*

The evidence above supports the **slide**: real corpora genuinely do not cover
Studies, so generating that class fills a real hole, whereas generating all 400
would mean evaluating the model largely against text produced by the same model
family.

### Resolved: the slide's strategy was adopted

Generation fills **Studies only** - the one class no real corpus covers. The
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

**Budget note.** A first run stopped at 77 rows on `BudgetExceeded` - the
per-session request cap in `backend/.env` (`MAX_REQUESTS_PER_SESSION`, default
100) working as designed. The full run used a raised cap for the one-off build:

```bash
MAX_REQUESTS_PER_SESSION=400 python -m eval.build_dataset --generate --per-category 120
```
