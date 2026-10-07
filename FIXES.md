# Outstanding fixes

Everything still open, ordered by marks-per-hour, then what has been closed and
how. Each open item says what is wrong, why it matters, and what "done" looks
like.

Every figure here was measured, not estimated. Where something is a judgement
call rather than a task, it says so.

Status at time of writing (2026-10-07): **602 backend tests passing (2 skipped,
8 expected failures), 178 frontend tests passing.**

Item numbers are kept from earlier versions of this file, because code and other
documents cite them; new items continue from 16.

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
so it cannot be automated. Set `GMAIL_OWNER` to the login that owns the mailbox,
or every account that can sign in sees it.

**Do this well before the demo, not on the day.** Things only a live run
reveals: label-name quirks, unusual MIME in a real message, an account-level
Google setting.

**Done when:** someone emails the project address, Reload inbox shows it
classified, and Gmail still shows it unread.

> The token expires every 7 days while the app is in Testing. Run
> `python -m backend.scripts.gmail_auth --check` the day before any demo.

---

### 3. Browser smoke test (NFR-02, SR-01) — 15 minutes

**Partly done.** On 2026-10-07 the app was driven in headless Edge, which is
Chromium: sign-in, the inbox at 1000, 1366 and 1920 pixels wide, a typed command
end to end against the real model, and Settings scrolling. That check found a
layout bug no jsdom test could — a long email or an open summary stretched the
reader past the window and scrolled the whole page — which is fixed in
`styles.css` and pinned in `styles.test.js`.

**Nobody has opened it in Firefox**, which is not installed on the development
machine. It has no `SpeechRecognition`, so SR-01's degraded path has still never
been seen.

**Done when:** a screenshot from Chrome and Firefox, and a note that in Firefox
the capability notice appears, Voice Commands is gone from the sidebar, and the
command bar still works: "summarise the latest email" opens the newest email and
summarises it, "read …" reads the summary aloud, and nonsense shows the pick-one
question.

---

### 16. Six more verified Work rows, for DR-01's 400 — about 2 hours

DR-01 asks for 400 emails, 100 per class. The set has 376, 94 per class, because
the Work relabel found 27 of 120 folder-labelled rows were not Work and the set
was rebalanced rather than topped up with unverified rows. Six more verified
Work rows make 100 per class; the other classes already have verified rows to
spare. 228 Work candidates exist.

```bash
python -m eval.label_candidates --build --category Work --source enron --out eval/data/review_work_new.csv
python -m eval.review_cli --category Work --file eval/data/review_work_new.csv
python -m eval.label_candidates --apply --category Work --review-file eval/data/review_work_new.csv
python -m eval.build_dataset --merge --per-class 100
```

`--build` refuses to overwrite a review file that already holds verdicts, and
`--apply` skips a candidate that is the same message as a row already in the
set. **A model must not do the reading**: the proposals come from a language
model, and promoting them without a human read makes the evaluation circular.

**Done when:** the merge writes 400 rows, the test split is run once and
recorded as a new run in `eval/BENCHMARKS.md`, and the rows the merge took are
dropped from `holdout_unscored.csv` (see `eval/data/README.md`).

---

### 17. A second, blind annotator — about 1 hour

382 of the first 383 verdicts accepted the model's proposed label unchanged, on a
tool that showed the proposal before asking. That is what anchoring looks like.

```bash
python -m eval.review_cli --category Work --file eval/data/review_work.csv --blind --annotator <name>
python -m eval.review_cli --category Work --file eval/data/review_work.csv --agreement --annotator <name>
```

`--blind` hides the proposal, the folder and the model's reason and writes to a
column of its own; `--agreement` reports raw agreement and Cohen's kappa.

**Done when:** a teammate who did not do the first pass has read at least 50
rows blind, and the kappa is written into `eval/data/README.md`.

---

### 4. Decide FR-07 (translation) — a decision, not a task

In the RTM at LOW priority. Not implemented: no route, no prompt, no schema, no
UI control. The build spec explicitly descoped it, and the README says only that
it was not attempted — a fact, not a justified descoping.

Pick one and write it down: **descoped with justification**, or **built**.
Leaving it merely absent is the bad option — a marker reads the RTM.

---

### 14. The product has three names — a decision

**MailKit** is the name in the code and the UI. **InboxIQ** survives only in
comments in four frontend files; **Inbox AI** (`inboxai.app`) is in the Week 11
wireframes. Pick one before the demo and the report.

---

### 18. Attachment text in summaries — a decision

Attachments are now listed — name, type and size — and their content still
never reaches a body, a summary or a model. Reading PDF text for summaries would
break that promise, which the README and the reading pane both make, so it needs
a team decision and its own test set before any code. It is new scope beyond the
RTM.

---

## Code and data

### 15. `.vscode/settings.json` is still tracked — 1 minute

It is in `.gitignore` but was committed before that, so edits still show as
changes. Run `git rm --cached .vscode/settings.json` and commit.

---

### 19. The IMAP source still downloads every attachment — half a day

`backend/adapters/gmail_source.py` fetches `BODY.PEEK[]`, every byte of every
attachment, to list names and sizes. The Gmail API source no longer does: it
asks for `format=full`, which leaves attachments behind as ids and sizes. IMAP
could do the same with `BODYSTRUCTURE` plus the text parts. It is the fallback
source, so this can also be left documented, as it is in the adapter's
docstring.

---

### 20. Seven misheard names still resolve to nothing

`tests/test_voice_resolver.py` pins 16 realistic mishearings ("sara",
"git hub", "fit three one six four"). Joining split words rescued five; 9 now
resolve and 7 still do not, each a strict `xfail` that fails the moment a change
rescues it. Nothing resolves to the **wrong** email, and an unresolved
reference makes the UI ask, so this is a convenience gap, not an error.

---

### 21. The 0.7 confidence threshold is calibrated for one model

`CLASSIFY_CONFIDENCE_THRESHOLD` was tuned on gpt-4o-mini. Claude Sonnet and Opus
send about a fifth of emails to Review at the same threshold
(`eval/data/compare/REPORT.md`), so switching models without re-tuning it on dev
would read as a worse classifier. Make it per-model configuration, chosen on
dev, and count misfiled emails as well as strict accuracy when choosing.

---

### 22. Typed commands miss what spoken ones miss

The command bar uses the voice intent classifier, so it declines the same short
or indirect commands ("let tom know i can make it on friday", "reply please").
It declines rather than guesses, and shows the pick-one question. A confident
command that names no email, with none open, makes a fresh intent call when
re-run; the result is not kept.

---

## Done since the last version of this file

| # | Item | How it was closed |
|---|---|---|
| 2 | Verify the Work relabel | All 120 rows verified; every real label in the set is `human`. The rebuild command that would have overwritten them is fixed: human rows win id collisions, `--merge` refuses an unbalanced set, and the README gives the command that reproduces `dataset.csv` exactly |
| 5 | FR-05 intent prompt | Route (b). 60 held-out transcripts and 22 probes were written first, then the prompt was fixed: **91.7–95.0% over three runs, no wrong dispatch in 180**. 86.7% stands for the earlier prompt. `eval/BENCHMARKS.md`, FR-05 |
| 6 | The ≥90% test | Passes with the fixed prompt, and a second gate on the held-out 60 was added. Both run only with `RUN_LLM_EVAL=1`. The threshold was not touched |
| 7 | FR-02 headline not reproducible | Run 12 recomputes from `test_preds_run12.csv`; `--out` now records the settings in every row and refuses to overwrite an earlier run |
| 8 | Stale NFR-01 line | Replaced by a measured figure |
| 9 | `dev_preds.csv` unexplained | Identified in `eval/BENCHMARKS.md` as a run that lost 18 rows |
| 10 | NFR-01 cold load 8.2 s | One email per call, 25 at once: **median 2.0 s over 8 cold loads of 25 emails, all under 5 s** (`eval/cold_load.py`). The in-process latency window still resets on restart and would understate p95 behind several workers — a limitation, not a bug |
| 11 | Save `claims_checked` | `evaluate_grounding.py` writes it |
| 12 | No React component tests | 178 frontend tests in 14 files, including component tests for the inbox, the reading pane, the voice view, the command bar and the shared intent question |
| 13 | FR-04/05 priority | **HIGH.** The PDF draws an orange MED badge and then a red HIGH badge over the same cell; the rendered slide shows HIGH, and the README now says so |

Found in the October review, not previously listed, and fixed:

| Problem | Fix |
|---|---|
| Batched classification cost 13 points of strict accuracy and caused the slow cold load | One email per call (runs 11 and 12; confirmed on a holdout nobody had scored, 63.4% → 87.0% strict) |
| FR-02's "meets 80% on real email" counted only answered emails: 73.9% strictly | Figures quoted strictly, Review counted as a miss: 89.4% on real email now |
| The README, `BENCHMARKS.md` and the dataset README contradicted the data | Brought in line |
| The recogniser language followed the browser's UI language | en-AU by default, chosen in Settings |
| "The latest email" picked the newest Work email | Candidates sent newest first with `received_at`, and re-sorted on the server |
| "Processed in your browser" was inaccurate | "Our server never receives your audio" |
| A long inbox lost its newest emails to the 100-candidate cap | The route reads up to 1,000 and keeps the newest 100 |
| Both Gmail sources downloaded every attachment on every inbox load | The Gmail API source uses `format=full` (IMAP: item 19) |
| An attached email's text was read into the body, and so reached the model | Body walkers skip an attachment and everything inside it, on both paths |
| Image-only marketing email cleaned to nothing | Image alt text kept; HTML used when the plain-text part cleans to nothing |
| The preprocessor cut a marketing email at its first "unsubscribe" line | A footer phrase cuts only when what follows it is footer |
| The grounding check flagged reformatted dates ("14JUL" → "July 14") | Compared by meaning; narrowed after review so "24/7", "may" and "SAT" vouch for nothing |
| One hostile email could stall every inbox load (cleaning was quadratic: 48 s for 30,000 "Thanks" lines) | Linear: under a tenth of a second on each case, pinned by tests |
| An email body could forge the `<email id>` delimiter of a batched prompt | One email per call leaves nothing to pre-empt; it remains possible under `CLASSIFY_BATCH_SIZE=20` |
| `--build` could overwrite a review file holding verdicts; `--apply` could add a duplicate of a test row | Both refused, with tests |

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
| **One email per call costs 2.5× as much to classify** | US$0.15 per 1,000 emails against US$0.06, for +13.5 points strict and a cold load under 5 s. About 38 users still fit inside the US$5/week budget on the comparison report's usage profile. `CLASSIFY_BATCH_SIZE=20` reverts it. |
| **Joined words are matched exactly, never fuzzily** | "git hub" must match a sender or subject exactly to count as GitHub. Fuzzy-matching the joins was tried: "read the one from the deals team" joined to "thedeals", 0.82 similar to "techdeals", and an unrelated request went to TechDeals. A wrong email is worse than being asked. A single misheard name is still fuzzy-matched, scored below an exact match. |
| **A bare "14/7" in an email does not vouch for "July 14"** | A numeric date in the source needs its year, or "24/7" and "1/2" vouch for dates nobody wrote. A false flag is the cheaper mistake. |
| **Typed commands run without a confirm step** | The same 0.6 confidence floor as voice; the actions are summarise, read and draft, and nothing is ever sent. Typed text cannot be misheard. |
