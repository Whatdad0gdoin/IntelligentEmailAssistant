# Outstanding fixes

Everything still open, ordered by marks-per-hour. Each item says what is wrong,
why it matters, and what "done" looks like.

Every figure here was measured, not estimated. Where something is a judgement
call rather than a task, it says so.

Status at time of writing: **348 backend tests, 84 frontend tests, all passing.**

---

## Blocked on a person (nobody else can do these)

### 1. Connect Gmail — 10 minutes

The Gmail API source is built and tested but **has never touched real Gmail**.
Every test uses a fake service, which is what lets the suite prove read-only,
but it means no message has made the round trip.

```
EMAIL_SOURCE      = (unset -> fixture)
OAuth client file = not created yet
OAuth token file  = not created yet
```

Setup is in `README.md` under *Read a real Gmail inbox*. Needs a Google account,
so it cannot be automated.

**Do this well before the demo, not on the day.** Things only a live run
reveals: label-name quirks, unusual MIME in a real message, an account-level
Google setting.

**Done when:** someone emails the project address, Reload inbox shows it
classified, and Gmail still shows it unread.

> The token expires every 7 days while the app is in Testing. Run
> `python -m backend.scripts.gmail_auth --check` the day before any demo.

---

### 2. Verify the Work relabel — ~30 minutes

120 rows in `eval/data/review_work.csv`, **0 verified**. 27 are staged as not
Work (13 Personal, 13 Promotions, 1 Studies) — spam, club flyers, fantasy
football, a message from a spouse.

```bash
python -m eval.review_cli --category Work      # 27 contested rows come first
python -m eval.label_candidates --apply --category Work --source enron
python -m eval.build_dataset --merge
```

**A model must not do this.** The proposals came from a language model, and
`eval/review_labels.py` explains why promoting them without a human read makes
the evaluation circular: the emails that confuse the classifier are
disproportionately the ones that confused the labeller. `--apply` refuses while
any row is unverified, by design.

**Worth about +2 points** (83.3% → 85.3% indicative). Report it as a
*measurement correction*, not a better classifier — on 7 of the 10 rows that
change, the model was already right and was being marked wrong against a bad
label.

---

### 3. Browser smoke test (NFR-02) — 15 minutes

The RTM says *"fully functional in Chrome"*; SR-01 says Firefox and Safari must
degrade gracefully. **Nobody has opened it in Firefox.** No browser-driven test
exists, so NFR-02 currently rests on manual use and is marked in the README as
"done by construction, not by test".

Firefox is the interesting one: it has no `SpeechRecognition`, so the SR-01
capability notice should appear and Voice Commands should vanish from the
sidebar rather than dead-end.

**Done when:** a screenshot from each of Chrome, Edge and Firefox, and a note
of what degraded in Firefox.

---

### 4. Decide FR-07 (translation) — a decision, not a task

In the RTM at LOW priority. Not implemented: no route, no prompt, no schema, no
UI control. The build spec explicitly descoped it.

Pick one and write it down: **descoped with justification**, or **built**.
Leaving it merely absent is the bad option — a marker reads the RTM.

---

## Code and data

### 5. FR-05 intent prompt — `read` does not cover summaries

**Measured: 86.7% (26/30), criterion ≥90% NOT met.**

Three of the four errors are one gap. `INTENT_SYSTEM` in
`backend/orchestrator/prompts.py` defines `read` as *"an email read out loud"*
and never covers reading out an **existing summary** — which is exactly what the
app's own summarise-then-read flow produces:

| Transcript | Expected | Got |
|---|---|---|
| read aloud the summary of the latest email | read | `unknown` |
| play the summary for the github alert | read | **summarise** (only wrong dispatch) |
| say the summary out loud | read | `unknown` |
| whats the enrolment email about | summarise | `unknown` |

The fourth is an indirect question with no summarise verb.

**Methodological trap, read before fixing.** These 30 transcripts are the
acceptance set. Tuning the prompt against the failures they exposed and then
re-measuring on the same set is training on the test set, and the resulting
number would be optimistic. Two honest routes:

- **(a)** Fix the prompt, re-measure, publish **both** numbers, and state that
  the fix was informed by these transcripts.
- **(b)** Write new held-out transcripts first, then fix, then measure on those.

(b) is more rigorous. Either way **86.7% stands as the figure for the shipped
prompt** — a re-run is a new measurement, not a correction.

---

### 6. `test_voice_intent.py` asserts ≥90% and will now fail

`test_thirty_transcripts_dispatch_at_or_above_ninety_percent` asserts
`rate >= 0.90`. Under `RUN_LLM_EVAL=1` with a real key it now **correctly
fails** at 86.7%. It is a working test reporting a real result.

Options: leave it red as an honest signal, or `xfail` it carrying the measured
86.7% and the reason.

**Do not lower the threshold to make it green.** That buries the finding.

---

### 7. The FR-02 headline is not reproducible

`eval/BENCHMARKS.md` quotes **run 8: 92.9% coverage / 83.0% accuracy** as the
shipped-configuration headline. But the only saved prediction file,
`test_preds_mini.csv`, computes **92.1% / 83.3%** — which is run 9. Run 8's
per-row predictions are gone or were overwritten.

Verified independently twice.

So the number most likely to appear on a slide cannot be regenerated from the
repository. Either:

- **quote 83.3%**, which a marker can reproduce from a committed file, or
- re-run the test split to regenerate run 8's predictions.

The difference is inside the documented noise band (run-to-run spread 0.3), so
this is about reproducibility, not accuracy.

*Sub-finding:* the per-class table printed under *"Shipped-configuration detail
(run 8)"* actually matches run 9 exactly. Its confusion matrix is already
labelled run 9. The `text_origin` breakdown and confusion matrix reproduce
exactly.

---

### 8. `eval/BENCHMARKS.md` line 27 is stale

```
| NFR-01 latency | p95 | not yet instrumented |
```

It **is** instrumented now — `GET /api/metrics` exists. But no p95 has been
recorded against the real model, so the honest wording is **"instrumented, not
yet measured"**, not a number.

See item 10 for the number that should go there.

---

### 9. `dev_preds.csv` matches no recorded run

Computes **82.2% coverage / 78.4% accuracy / 64.5% strict**. The nearest entry
is run 5, off by −9.4 coverage and +6.0 accuracy — far too large to be a typo,
and 58 of its 214 predictions differ from `predictions.csv`.

No published figure depends on it and nothing in the notebook uses it, so this
is data hygiene rather than a wrong result. Either identify which run it came
from and record it, or delete it. An unexplained prediction file in an
evaluation directory invites exactly one question at a viva.

*(`predictions.csv` = run 2 and `test_preds.csv` = run 7 both reconcile
exactly.)*

---

### 10. NFR-01 fails on first load — 8.2s against a 5s target

The instrumentation found this on its first live run:

```
GET /api/inbox   cold: 8218 ms      warm: ~230 ms      target: 5000 ms
p95_within_target: false
```

The cold load classifies 8 emails through the model. The per-message cache then
makes every later load ~0.23s. **The cold load is the one a marker sees.**

Options: warm the classification cache at startup, or report cold and warm
separately with the cache named as the mitigation. Quoting one pooled number
hides it.

Then record the measured p95 in `eval/BENCHMARKS.md` (item 8).

> The latency window is per process and resets on restart. Fine for the dev
> server; it would understate p95 behind multiple WSGI workers. Belongs in the
> limitations section.

---

### 11. `evaluate_grounding.py` does not save `claims_checked`

One-line fix. The script **already computes** claims-checked-per-output in
order to print it, but `--out` writes only
`task,id,category,text_origin,grounded,flag_count,flags,subject`.

Consequence: the DR-02 notebook cannot recompute it and has to fall back to a
lower bound plus a source-side proxy. `BENCHMARKS.md` argues — correctly — that
a groundedness rate is vacuous without it, since a rate over outputs containing
nothing checkable reads 100% however badly the model behaved.

Add the column, and the notebook can compute the figure the argument depends on.

---

## Smaller, still worth doing

### 12. No React component tests

`frontend/package.json` has **no jsdom, no happy-dom, no Testing Library**, so
nothing mounts a React tree. The 84 frontend tests cover pure logic
(`search.js`), the API client, and the stylesheet — real coverage, but "84
frontend tests" should not be read as UI coverage.

This is the project's largest testing gap. Worth one honest sentence in the
limitations section even if it is not closed.

---

### 13. RTM priority for FR-04 / FR-05 is ambiguous in the source

The Week 11 deck renders their priority cells with `HIGH` and `MED` overlaid in
the text layer (extracts as `HMIGEDH`). The README currently writes `MED/HIGH`
with a footnote rather than guessing.

Settle it against the signed RTM and make the deck, the README and the report
agree.

---

### 14. The product has three names

**MailKit** (the code and UI), **Inbox AI** at `inboxai.app` (the Week 11
wireframes), **InboxIQ** (the original filename). Pick one before the demo and
the report.

---

### 15. `.vscode/settings.json` is untracked

It would be swept in by `git add -A`. Personal editor config: gitignore it, or
stage files deliberately.

---

## Deliberately not fixed

These look like gaps and are not. Each is a decision with a reason.

| Thing | Why it stays |
|---|---|
| **No send path anywhere** | FR-03 asks for exactly this. `tests/test_draft.py` asserts no send route exists and no mail-sending library is imported under `backend/`. That guard is the evidence. |
| **JWT does not survive a page reload** | Spec section 5.1: in memory, never `localStorage`. |
| **IMAP kept alongside the Gmail API** | Plan B if the 7-day OAuth expiry bites on demo day. Needs no Google Cloud project. |
| **The local SMTP server writes mail to disk** | It is the mail-server tier, not the assistant. `tests/test_mailserver.py` asserts nothing under `backend/` imports it. |
| **`eval/notebook.ipynb` is ~308 KB** | Outputs are stored deliberately, so a marker reads results without running it. |
