# Intelligent Email Assistant

FIT3164 · Group DS-25 · Project 10

An LLM-powered email assistant: summarisation with traceable provenance,
categorisation, human-in-the-loop reply drafting with tone control, and voice
interaction. React SPA → Flask REST API → LLM orchestrator → OpenAI API.  

## Build status

Tracked against the Week 11 Requirements Traceability Matrix rather than the
build spec's step order, because the RTM is what the project is graded on and
the step order no longer says anything useful: all ten steps are now built, so a
list of them reads as ten ticks and hides where the real gaps are. What is left
is not a missing step — it is two missing *numbers* and one requirement nobody
started.

**FR-07 (translation) is not implemented at all. NFR-01 and FR-05 are both built
but not yet evidenced — no p95 has been recorded and the 30-transcript intent
accuracy has not been run.** Everything else in the table is built on both tiers
and reachable in the browser.

| ID | Requirement (RTM wording, abbreviated) | Pri | Status | Implementation, and how it is checked |
|---|---|---|---|---|
| FR-01 | Summarise unread emails, 2–3 sentences each | HIGH | Done | `POST /api/summarise` → `orchestrator/summarise.py`, which enforces the sentence count in Python and retries once. Rendered in place by `components/ReadingPane.jsx`, with a Verified/Unverified chip and a per-sentence "show source" that highlights the passage a sentence came from. Groundedness **93.0%** |
| FR-02 | Auto-categorise into Work / Personal / Promotions / Studies, 80% | HIGH | Done · target partly met | `POST /api/classify` and the batch inside `GET /api/inbox`. **83.0% on the held-out test split (n=266), but 78.1% on real email only** — see below and `eval/BENCHMARKS.md` |
| FR-03 | Draft a reply; editable area; not sent without explicit approval | HIGH | Done | `POST /api/draft` returns text and nothing else. The draft lands in an editable textarea with an **Approve** button; approval marks the text reviewed and stops there. There is no send route and no mail-sending library in the backend, both asserted by `tests/test_draft.py`. Groundedness **97.4%** |
| FR-04 | Read summaries aloud via Web Speech API ("Read Aloud") | MED/HIGH¹ | Done | `hooks/useSpeech.jsx`, browser-side only, no backend. Reads the *summary* sentences, never the raw body; fetches a summary first if none exists yet, so the button cannot read email text. The control is hidden outright when the browser has no `speechSynthesis` |
| FR-05 | Accept spoken voice commands; classify intent | MED/HIGH¹ | Done · acceptance not yet measured | `views/Voice.jsx` (recognition in the browser, transcript only leaves it) → `POST /api/voice/intent`. Below the confidence floor it shows the transcript back and asks rather than guessing. The ≥90% dispatch criterion needs a real API key and `eval/BENCHMARKS.md` records it as **not yet run** |
| FR-06 | Adjust tone of the drafted reply (Formal / Casual / Professional) | MED | Done | `TONES` in `orchestrator/schemas.py`, register-only guidance in `orchestrator/prompts.py`, optional `tone` on `POST /api/draft` (an unknown value is a 400, not a silent fallback), and a tone row on the draft panel that regenerates immediately. The tone is echoed back in the response so the UI cannot label a draft with a tone it was not written in |
| FR-07 | Translate email content or drafted reply into a chosen language | LOW | **Not implemented** | Nothing exists: no route, no prompt, no schema, no UI control. Deliberately still listed here rather than dropped from the docs |
| FR-08 | On login, retrieve emails and display them grouped by category | HIGH | Done | `GET /api/inbox` returns five groups already grouped; `views/Inbox.jsx` renders them with category chips, a flat "All" view, search, and a Review bucket that carries its explanation inline |
| NFR-01 | AI responses returned and displayed within a few seconds | HIGH | Done · not yet measured | `middleware/timing.py` times every route into a bounded in-process ring; `GET /api/metrics` reports nearest-rank p50/p95/max and an `over_target` count against the 5 s target, overall and per route, and returns `null` rather than `0` on an empty window so an unmeasured figure cannot read as a pass. Covered by `tests/test_metrics.py` (28 tests). **What is missing is the number:** no p95 run has been recorded in `eval/BENCHMARKS.md`, so the requirement is instrumented but not yet evidenced. Two mitigations predate the timer — batch classification is one round trip rather than one per email, and the inbox renders a skeleton while that call is in flight |
| NFR-02 | Browser-accessible; no install or plugin; works in Chrome | HIGH | Done by construction, not by test | A React SPA over a REST API; `npm run build` produces a static bundle and nothing needs an extension. There is no browser-driven or end-to-end test in this repo, so "fully functional in Chrome" rests on manual use, not on a green tick. Voice is the one browser-gated part, and SR-01 covers it |
| NFR-03 | Email content not stored permanently; no body data between calls | HIGH | Done | Bodies are fetched per request, preprocessed in memory and dropped; the cache holds model output only; logs carry character counts rather than content. `tests/test_no_body_in_logs.py` runs a full session against a real log file on disk and greps it |
| NFR-04 | Login required before email data or assistant features | HIGH | Done | One fail-closed `before_request` guard with a two-entry public allowlist. `tests/test_auth.py` enumerates the URL map rather than listing routes by hand, so it covers all seven protected routes and picked up `/api/metrics` the moment that was registered, with no change to the test |
| SR-01 | Voice restricted to Chrome/Edge; notify on unsupported browsers | MED | Done | `lib/capabilities.js` reads `speechSynthesis` and `SpeechRecognition` once at load. Without STT the Voice destination is removed rather than shown as a dead end; without TTS the Read Aloud button is not rendered; a persistent, non-blocking notice says which one is missing. Every voice action is also a button |
| DR-01 | Labelled dataset of 400 emails, 100 per category | MED | Done, exceeded — with a label caveat | `eval/data/dataset.csv`: **480 rows, 120 per class, 360 real / 120 synthetic**. The RTM asks for an AI-generated set; the Week 11 dataset slide asks for real mail. The slide won — generation fills Studies only, the class no real corpus covers. See the caveat below |
| DR-02 | Labelled set as ground truth: accuracy, precision, recall, F1, matrix | MED | Done | `eval/evaluate_classifier.py` prints coverage, accuracy and strict accuracy, per-class precision/recall/F1, macro-F1 and a confusion matrix. Every run is logged in `eval/BENCHMARKS.md` |

¹ The RTM slide's priority cell for FR-04 and FR-05 renders two values on top of
each other (`HIGH` and `MED` overlaid), so this table does not pick one.

### Where this build falls short, precisely

- **NFR-01 has no measured figure.** The timer and `GET /api/metrics` both work
  and are tested, but nobody has yet driven enough traffic through the app to
  fill a window and recorded the p95 in `eval/BENCHMARKS.md`. Until that exists,
  "responses within a few seconds" is an implemented capability and an unproven
  claim, and the endpoint is careful not to let an empty window look like a pass.
- **FR-07 is not implemented at all.** It is LOW priority in the RTM and was
  not attempted. Nothing partial exists to describe.
- **FR-02 meets its 80% target pooled and misses it on real email.** 83.0%
  covers the whole held-out split; the real-email subset scores **78.1%** and
  the synthetic subset 98.4%, so part of any pooled figure is the model telling
  real mail from model-written mail, which is not FR-02. `eval/BENCHMARKS.md`
  is explicit that 78.1% is the number to quote.
- **FR-05's acceptance criterion has not been run.** The classifier and the
  harness both exist; the 30-transcript accuracy figure does not, because the
  run costs real API calls. The corresponding backend test is skipped rather
  than stubbed, for the same reason.
- **DR-01's Work labels are known to be wrong.** All 120 Work rows come from an
  Enron folder heuristic; reading them found **27 (22.5%) mislabelled**.
  Corrections are staged in `eval/data/review_work.csv` and have **not** been
  applied, so the reported accuracy understates the classifier.
- **There is no send path, and that is the requirement.** FR-03 asks for a
  reply that is not sent without explicit approval; this build has no send
  route, no mail-sending library and no recipient field anywhere in the
  backend. Approve means "reviewed", and the UI says so.

## API

Every route below is in the live URL map, checked against it rather than written
from memory. All of them require
`Authorization: Bearer <jwt>` except `POST /api/auth/login` and
`GET /api/healthz`, which are the entire public allowlist.

| Route | Requirement | Response, and what it does |
|---|---|---|
| `POST /api/auth/login` | NFR-04 | `{token, expires_in}`. Public. No user enumeration: unknown email and wrong password are indistinguishable in body, status and timing. |
| `GET /api/healthz` | — | `{status: "ok"}`. Public. Liveness only; returns no user or email data. |
| `GET /api/inbox` | FR-08, FR-02 | `{groups: {Work, Personal, Promotions, Studies, Review}}`. **Snippets only, no bodies.** Runs the classification batch itself and caches labels per email id, so a re-fetch costs no API calls. |
| `GET /api/inbox/<id>` | FR-08 | One message with its **preprocessed** body — quoted chains, signatures and HTML already stripped — so the reader shows the same text the orchestrator summarises. Fetched fresh every time and never cached (NFR-03). |
| `POST /api/summarise` | FR-01 | `{email_id, summary[], action_items[], provenance[], grounded, ungrounded_flags[]}`. 2–3 sentences, enforced in Python with one retry. `action_items` are `{text, source_sentence}`; `provenance` is `{sentence, spans[]}` with character offsets into the preprocessed body, computed deterministically and never asked of the model. Cached per email id. |
| `POST /api/classify` | FR-02, DR-02 | `{results: [{id, category, confidence, evidence}]}`. Batch, limit 100 per call. Takes bodies rather than ids so the evaluation set need not exist as a mailbox; results from supplied bodies are deliberately **not** cached, or an eval run could poison the inbox's labels. |
| `POST /api/draft` | FR-03, FR-06 | `{draft, grounded, ungrounded_flags[], tone}`. Optional `instruction` (string) and optional `tone` (`neutral`/`formal`/`casual`/`professional`; anything else is a 400). Returns text only — **no send endpoint exists.** |
| `POST /api/voice/intent` | FR-05 | `{intent, target_email_id, confidence}` where `intent` is `summarise` / `read` / `draft` / `unknown`. Optional `emails` and `alternatives` arrays; see the deviations below. |
| `GET /api/metrics` | NFR-01 | `{window_size, units, percentile_method, p95_min_samples, target_seconds, p95_within_target, overall, routes}`. Each block is `{count, p50_ms, p95_ms, max_ms, over_target, enough_for_p95}`; empty blocks return `null` rather than `0`, so an unmeasured window cannot read as a pass. Authenticated, like everything else under `/api`, and excluded from its own window so polling it cannot evict the samples it reports. The frontend does not call it; it is there for measurement, not for the UI. |

Failure codes: `400` malformed request, `404` unknown email id, `422` nothing
left to summarise after preprocessing, `429` session request cap spent, `502`
the model would not produce valid output after a retry, `503` the AI service or
mailbox is unreachable. No route returns a success shape on failure, and no
error response echoes the request payload back (NFR-03).

### Three deliberate deviations from the written contract

All three are additive; none changes a documented field.

1. **`GET /api/inbox` runs the classification batch itself.** The contract says
   the inbox returns emails already grouped and that categories come from
   `/api/classify` as one batch on login. Rather than make the frontend call
   two endpoints and group the result itself, `/api/inbox` calls the classifier
   internally as a single batch and caches per email id, so a re-fetch costs no
   API calls. `/api/classify` remains a real endpoint for the evaluation set.
2. **`POST /api/voice/intent` accepts an optional `emails` array.** The response
   needs `target_email_id`, but an email id is parsed data and rule 5 keeps
   parsed data away from the model. So the model returns only the words the user
   used ("the one from Sarah"), and the backend matches that against the sender
   names and subjects the caller passes in. Omit `emails` and `target_email_id`
   is `null`, which the contract already allows. An ambiguous reference also
   returns `null` rather than a guess.
3. **`POST /api/voice/intent` also accepts an optional `alternatives` array.**
   The browser's recogniser ranks several hypotheses for one utterance and the
   top one is often not the one that caught the name. Pooling them widens the
   deterministic target match without widening what the model sees: intent is
   still classified from the primary transcript alone, and the alternatives feed
   target resolution only.

The frontend calls all of these except `/api/healthz` and `/api/classify` —
`/api/classify` exists for evaluation, and the inbox gets its labels from
`/api/inbox`. Every call goes through the one fetch client in
`frontend/src/api/client.js`, which is what makes the JWT attachment (NFR-04)
and the 401-anywhere-returns-to-login rule enforceable in a single place.

## Setup

### Quick start

Double-click **`start.bat`**, or from a terminal:

```powershell
.\start.ps1
```

That one command checks Python and Node are present, creates `backend/.env`
from the example if it is missing, installs any missing Python and Node
packages, downloads the spaCy model, frees ports 5000 and 5173, starts both
servers in their own windows, waits until they answer, and opens the browser.

Everything runs in that one window, with each server's output prefixed and
colour-coded. **Ctrl+C stops all of them.**

| Flag | Effect |
|---|---|
| `-Mail` | also run the local SMTP server (see below) |
| `-MailLan` | as `-Mail`, but accepts mail from other devices on the network |
| `-SkipInstall` | skip the dependency check, for a faster restart |
| `-Windows` | one separate window per server, for when one is crashing |
| `-Stop` | stop anything still running |

Run it from a terminal you own. A server started inside an agent or IDE task
session is a child of that shell and dies when the session ends, which shows up
in the browser as "Cannot reach the API server".

### First run

`start.ps1` creates `backend/.env` for you but cannot fill it in. Set:

```bash
# a long random string
python -c "import secrets; print(secrets.token_urlsafe(48))"

# an account (prints a JSON fragment for AUTH_USERS)
python -m backend.scripts.hash_password
```

and add your `OPENAI_API_KEY`. Without it the app runs and login works, but
summarise, classify and draft return 503.

### Send a real email to it

In the default `fixture` mode the app reads a mailbox on disk, so it can be fed
real mail without a mail provider. `backend/mailserver.py` is a small SMTP server
that delivers into that mailbox, so you can send the assistant an actual email
over SMTP and read it in the app.

```powershell
.\start.ps1 -Mail            # app + a local mail server on port 2525
python tools/send_test_email.py       # sends one, in another terminal
```

Then reload the inbox. The message is parsed from its real headers, classified
like any other, and can be summarised, drafted against and read aloud.

`--category work|studies|personal|promotions` picks a different preset, and
`--interactive` lets you type your own subject and body. Any SMTP client works
too: host `localhost`, port `2525`, no auth, no TLS.

To send from a phone or another machine on the same network:

```powershell
.\start.ps1 -MailLan
```

That binds the receiver to all interfaces. It has no authentication and no TLS,
so use it on a network you trust and stop it when you are done. It is a
development tool, not a mail host, and it cannot receive from the public
internet without port forwarding.

**On NFR-03.** The mail server writes messages to disk, because that is what a
mailbox does. The assistant still writes nothing: these are separate tiers and
separate processes, and `tests/test_mailserver.py` asserts that no module under
`backend/` imports the mail server. Received mail is delivered to
`backend/mailbox/`, which is gitignored and kept apart from the committed demo
fixtures so the test suite always sees the same six messages.

### Read a real Gmail inbox (so someone can email the app)

Gmail cannot deliver to the local SMTP server: inbound mail needs a public MX
record, a reachable port 25 and TLS on a domain you own. So a Gmail inbox is
*read*, over the Gmail API. Anyone emails that address; the app shows it.

**Use a Gmail account made for the project**, e.g. `ds25.mailkit@gmail.com`.
Every message the app reads has its body sent to the model for classification
and summarisation. A Monash address will probably not work: university Google
Workspace accounts usually block unapproved third-party apps.

#### One-time Google Cloud setup (about 10 minutes)

Signed in to <https://console.cloud.google.com> as the project account:

1. **Create a project** (any name).
2. **APIs & Services → Library** → search *Gmail API* → **Enable**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform):
   - User type **External**, app name anything, your address as support email.
   - **Scopes**: you can skip this; the app asks for `gmail.readonly` itself.
   - **Audience → Test users**: add the Gmail address you will connect.
   - Leave publishing status as **Testing**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   application type **Desktop app**. Download the JSON.
5. Save it as `backend/secrets/gmail_client.json` (the folder is gitignored).

#### Connect

```bash
python -m backend.scripts.gmail_auth
```

A browser opens. Sign in as the project account and allow read access. Google
will warn that the app is unverified — that is expected for an app in Testing
that you made yourself: **Advanced → Go to (app name)**. The script then prints
which account connected and how many messages it holds.

Set `EMAIL_SOURCE=gmail` in `backend/.env` and restart with `.\start.ps1`.

#### Things to know before a demo

- **Access expires every 7 days** while the app is in Testing. Google's rule,
  not this app's. The inbox shows *"Gmail access has expired... Reconnect
  with: python -m backend.scripts.gmail_auth"* — run it, and it is back.
  Check the day before with `python -m backend.scripts.gmail_auth --check`.
- **New mail does not appear by itself.** There is no push; press
  **Settings → Reload inbox** after someone sends. Say so out loud in a demo so
  the pause does not read as a fault.
- **First mail from a new sender may go to Spam**, which the app does not read.
  Send a test beforehand and mark it *Not spam*.
- **The demo fixtures are replaced**, not joined: Gmail mode shows only Gmail.
- Only the newest `GMAIL_LIMIT` (25) messages load, and each is classified once
  and then cached by message id.

`GMAIL_MAILBOX` takes any label, so applying a `demo` label by hand and setting
`GMAIL_MAILBOX=demo` limits the app to messages you chose.

#### Why the API and not IMAP

**It is read-only because Google enforces it.** The token is granted exactly one
scope, `gmail.readonly`, so Google's own servers refuse any modify, trash, label
or send, whatever the code asks for. The adapter additionally calls only
`messages.list`, `messages.get` and `labels.list`, and
`tests/test_gmail_api_source.py` fails if it tries anything else. Reading mail
here never marks it read in Gmail.

**No password is stored.** The token in `backend/secrets/` can be revoked at
<https://myaccount.google.com/permissions> without changing any password, or
with `python -m backend.scripts.gmail_auth --revoke`.

The costs: the Google Cloud setup above, the 7-day expiry, and `gmail.readonly`
being a *restricted* scope — publishing the app for other people would need
Google verification and a third-party security assessment.

#### Fallback: IMAP with an app password

If the Cloud setup is not an option, `EMAIL_SOURCE=gmail_imap` reads the same
inbox over IMAP. It needs 2-step verification and an app password from
<https://myaccount.google.com/apppasswords>, set as `GMAIL_USER` and
`GMAIL_APP_PASSWORD`, and `python tools/check_gmail.py` tests it. The trade-off:
an app password is permanent, full mailbox access in plaintext in `.env`.

Set `EMAIL_SOURCE=fixture` to go back to the demo mailbox.

### Manual start

```bash
python -m pip install -r backend/requirements.txt
python -m spacy download en_core_web_sm
python -m backend.run              # http://localhost:5000

cd frontend && npm install
npm run dev                        # http://localhost:5173
```


## Tests

```bash
python -m pytest tests/ -q     # 348 passed, 1 skipped
cd frontend && npx vitest run  # 84 passed, in 3 files
```

The skip is deliberate and is the FR-05 accuracy criterion, which needs the real
model. It is skipped rather than stubbed because a stubbed accuracy figure would
measure the stub. Run it for real with:

```bash
python -m eval.intent_harness              # full report, exits non-zero below 90%
RUN_LLM_EVAL=1 python -m pytest tests/test_voice_intent.py
```

What the backend suite covers, and what it does not:

- **Real behaviour, no stub anywhere near it:** preprocessing (reply chains,
  forwarded chains, HTML, signatures, truncation), grounding (fabricated
  numbers, times, days and names flagged; paraphrase and format differences
  not), evidence verification, provenance offsets, voice target resolution, the
  Gmail adapters' read-only surface, the SMTP receiver end to end, the
  architecture rules, and the log inspection test, which runs a full session
  against a real log file on disk and greps it.
- **Stubbed model, asserting on backend behaviour:** that a fabricated evidence
  span routes to Review, that a 1- or 4-sentence summary is retried once and
  then fails loudly, that the retry is charged to the session cap, that an
  unknown `tone` is a 400 and that the four tones do not send near-identical
  prompts. The assertions are about what the backend does with a given
  response, never about what a model produces.
- **Negative tests, which are the point of several files:** no send route in the
  URL map, no mail-sending library imported anywhere under `backend/`, no
  vendor SDK outside `orchestrator/client.py`, no model name outside
  `config.py`, no prompt built in a route, no application module importing the
  mail server, and no concrete request path, email id or body reaching the
  NFR-01 latency window or the `/api/metrics` response.

The frontend suite is three files and **no component-render tests**: there is
no jsdom and no Testing Library in `package.json`, so nothing here mounts a
React tree. What it does cover:

- `src/api/client.test.js` — the fetch client: 401 handling on sign-in versus
  anywhere else, token attachment, timeout versus network failure versus
  cancellation, and the `POST /api/draft` body construction including the tone
  field (FR-06).
- `src/lib/search.test.js` — which view the inbox shows for a given filter and
  query, and the matching rules, tested without a browser because the bug it
  replaced — every group rendering regardless of the chosen chip — was
  invisible in the JSX.
- `src/styles.test.js` — stylesheet regressions. Mechanical specificity and
  contrast checks, written after the Approve button rendered as a white
  rectangle because `.iq button` out-specified `.ai-approve`.

**Not covered:** the rendered UI. Summarise, Read Aloud, Draft, Approve, the
tone row, capability detection and the Voice view are all verified by hand in
the browser, not by an automated test. That is the largest testing gap in the
project and it is not hidden here.

## Evaluation

**`eval/BENCHMARKS.md` is the authoritative log.** Every measured figure is
recorded there in the order it was produced, with the command that produced it,
the split it ran on and the run-to-run spread. Nothing in it is estimated. The
headline numbers, all on the held-out test split with the shipped
`gpt-4o-mini` configuration:

| Requirement | Metric | Result |
|---|---|---|
| FR-02 categorisation | accuracy (test split, n=266) | 83.0% — **78.1% on real email only** |
| FR-01 summarisation | groundedness rate | 93.0% |
| FR-03 draft reply | groundedness rate | 97.4% |
| FR-05 voice intent | dispatch accuracy | not yet run |
| NFR-01 latency | p95 | instrumented, no run recorded yet |

The tooling:

- `eval/data/dataset.csv` (DR-01) - 480 rows, 120 per class, 360 real / 120
  synthetic. `eval/data/README.md` documents every column, where each class came
  from and what is wrong with it.
- `eval/build_dataset.py` - rebuilds the set from the Enron corpus, the
  HuggingFace set and the project's own generator.
- `eval/evaluate_classifier.py` (FR-02, DR-02) - coverage, accuracy, strict
  accuracy, per-class precision/recall/F1, macro-F1 and a confusion matrix,
  broken down by `provenance` and `label_source`.
- `eval/evaluate_grounding.py` (FR-01, FR-03) - groundedness rate over recorded
  `/api/summarise` and `/api/draft` responses, with the claims-checked count and
  which entity backend produced the figure.
- `eval/data/voice_intents.csv` - the 30 graded transcripts for FR-05.
  `voice_intents_unknown.csv` holds out-of-scope probes that must return
  `unknown`; they are not part of the graded 30.
- `eval/intent_harness.py` - runs the intent classifier over both and prints
  accuracy and a confusion table. Exits non-zero below 90%.
- `eval/label_candidates.py`, `eval/review_labels.py`, `eval/review_cli.py` -
  the human-review path. `--apply` refuses to run until a person has confirmed
  every row, because model labels used to grade a model are not an evaluation.

**For the report, three caveats that belong in the limitations section:**

- **Never quote the pooled categorisation figure alone.** Class and label source
  are correlated in this dataset, so part of any pooled number is the model
  telling real mail from generated mail. Report the real-email figure, and
  report coverage and strict accuracy alongside accuracy — `Review` is an
  abstention, not a wrong answer.
- **Groundedness is a string check, not a semantic one.** No flags means
  "nothing checkable is missing from the source", not "the summary is true",
  and a legitimate paraphrase can flag. Both directions matter.
- **ROUGE measures n-gram overlap with a reference summary.** It cannot detect
  hallucination — a fluent, wholly fabricated summary that reuses the email's
  vocabulary scores well. It also cannot be computed on this dataset at all,
  which holds labelled categories and no reference summaries. If ROUGE is
  reported for FR-01 it must appear alongside the groundedness rate and be
  explicitly caveated.

## Layout

```
frontend/src/
  api/         client.js -- the single fetch client; attaches the JWT, handles every 401
  components/  Dashboard (app shell), ReadingPane (FR-01/03/04/06 in place),
               GroundingNotice, SideItem, OpenAIMark
  views/       Login, Inbox (FR-08), Voice (FR-05), Settings (section 5.5)
  hooks/       useAuth, useInbox, useSpeech (FR-04), usePreference
  lib/         capabilities.js (SR-01), constants (categories, tones), search,
               highlight (provenance spans), format
backend/
  app.py       application factory
  config.py    every setting, environment-driven
  run.py       dev entry point
  mailserver.py  local SMTP receiver -- the mail-server TIER, imported by nothing
                 under backend/ (asserted in tests/test_mailserver.py)
  routes/      auth, health, inbox, ai (summarise/classify/draft), voice,
               metrics (NFR-01), support.py (shared error translation)
  orchestrator/  ALL LLM calls live here
    client.py      the only module that imports the OpenAI SDK
    schemas.py     JSON schemas; the category enum and the tone enum live here
    prompts.py     all prompt text, including the FR-06 tone guidance
    preprocess.py  quoting, signatures, HTML, truncation (section 4.2)
    grounding.py   evidence and entity verification (sections 4.3-4.6)
    provenance.py  where each generated sentence came from, as char offsets
    classify.py    FR-02      summarise.py  FR-01
    draft.py       FR-03/06   intent.py     FR-05
    cache.py       summaries and labels only, never bodies
    budget.py      per-session request cap
  adapters/    three email sources behind one interface -- fixture .eml mailbox,
               Gmail over the Gmail API (OAuth), Gmail over IMAP -- plus header
               parsing and the committed demo fixtures
  middleware/  jwt guard, log redaction, timing.py (NFR-01 latency window)
  scripts/     hash_password, add_user, gmail_auth
eval/          the labelled dataset (DR-01), the metric scripts (DR-02) and
               BENCHMARKS.md, the log of every measured figure
tools/         send_test_email.py, check_gmail.py
tests/         backend suite (pytest); frontend tests sit beside their modules
```

## Security and safety notes

- **NFR-04.** Auth is a single fail-closed `before_request` guard, not per-route
  decorators. Everything under `/api` requires a token unless it is on an
  explicit two-entry allowlist. Forgetting to allowlist a new route makes it
  return 401 - visible and safe - rather than shipping it unauthenticated.
  `tests/test_auth.py` enumerates the URL map, so a route added later is
  covered automatically; it currently checks seven protected routes.
  `/api/metrics` needed no auth decorator and got none — it was covered by the
  401 test the moment it was registered, which is the whole argument for the
  guard being central rather than per-route.
- **No user enumeration.** Unknown email and wrong password return an identical
  body and status, and a decoy hash is verified on the unknown-email path so
  both branches take the same time.
- **NFR-03.** The JWT lives in a JS module variable, never `localStorage`, so it
  does not survive a reload — that is the intended trade-off, not an oversight.
  The one thing the browser does persist is a boolean UI preference
  (`hooks/usePreference.jsx`, the voice on/off switch); no email content and no
  token ever touches storage. Server-side, bodies are fetched per request,
  preprocessed in memory and dropped; the cache holds model output only —
  summaries, labels and computed provenance offsets, never body text; the
  orchestrator logs character counts rather than content; and route error
  handlers log exception *frames* without exception messages, because a parse
  error raised mid-body carries the fragment it choked on. A redaction filter is
  the backstop. `tests/test_no_body_in_logs.py` runs a full session and greps a
  real log file. The one thing that deliberately outlives a request is the
  NFR-01 latency ring, and it holds `(route rule, duration)` pairs only: the
  *parameterised* rule such as `GET /api/inbox/<email_id>`, never the concrete
  path, because a real message id routinely carries the sender's domain. That is
  latency metadata about the server, not data about anyone's mail, and
  `tests/test_metrics.py` asserts that no concrete path, email id or body can
  reach the window or the response.
- **Rule 4.** The OpenAI SDK is imported in exactly one file
  (`orchestrator/client.py`) and no model name appears outside `config.py`.
  Both are asserted in `tests/test_api_contract.py`, which also checks that no
  route module builds a prompt and that the frontend knows no model name.
- **Rule 5.** Sender, recipient, subject, timestamp, message id and thread id
  are parsed from headers in `adapters/headers.py`. The model is asked only for
  `category`, `category_confidence`, summaries, drafts and intent. Two things
  that look like model output are deliberately computed instead: the voice
  `target_email_id`, matched against sender names and subjects in the backend,
  and the provenance offsets behind each summary sentence — asking a model to
  quote its own sources invites it to fabricate the quotation.
- **Budget.** The per-session cap is a guard rail against a runaway retry loop,
  not a billing control: it is in-process, resets on restart and is not shared
  between workers. Real spend limits belong in the OpenAI dashboard.
