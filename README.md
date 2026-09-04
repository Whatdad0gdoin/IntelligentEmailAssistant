# Intelligent Email Assistant

FIT3164 · Group DS-25 · Project 10

An LLM-powered email assistant: summarisation, categorisation, human-in-the-loop
reply drafting, and voice interaction. React SPA → Flask REST API → LLM
orchestrator → OpenAI API.  

## Build status

Implemented against the build spec, in order. **The backend for steps 3–6 and 9
is complete. No frontend work has been done since step 1 - the UI still renders
placeholder fixtures and is not yet wired to any of these endpoints.**

| Step | Scope | Backend | Frontend |
|---|---|---|---|
| 1 | Frontend audit and gap table | - | Done |
| 2 | JWT middleware + login end to end (NFR-04) | Done | Done |
| 3 | Orchestrator skeleton | Done | - |
| 4 | `/classify`, grouped inbox, Review bucket (FR-02, FR-08) | Done | **Not wired** |
| 5 | `/summarise` + grounding flags (FR-01) | Done | **Not wired** |
| 6 | `/draft` + Approve control (FR-03) | Done | **Not built** |
| 7 | Capability detection (SR-01) | n/a | **Not started** |
| 8 | TTS Read Aloud (FR-04) | n/a | **Not started** |
| 9 | STT + intent + harness (FR-05) | Done | **Not started** |
| 10 | Latency instrumentation, `/api/metrics` (NFR-01) | **Not started** | **Not started** |

Two things this means in practice:

- The inbox in the browser still renders `frontend/src/lib/mockEmails.js` and
  the AI buttons still show a "not functional yet" toast. `GET /api/inbox`
  returns the real grouped inbox, but nothing calls it yet.
- The **Approve control (FR-03) does not exist**. The backend has no send path
  and cannot acquire one - there is no send route and no mail-sending library
  anywhere in it, both asserted in `tests/test_draft.py` - but the deliberate
  user action that gates sending is a frontend control and has not been built.

Out of scope for this build: FR-06 (tone adjustment), FR-07 (translation). The
orchestrator takes a `system` prompt per call, so a tone parameter can be added
in `orchestrator/prompts.py` without touching a route or a view.

## API

All routes require `Authorization: Bearer <jwt>` except `/api/auth/login` and
`/api/healthz`.

| Route | Requirement | Notes |
|---|---|---|
| `POST /api/auth/login` | NFR-04 | `{token, expires_in}`. No user enumeration. |
| `GET /api/inbox` | FR-08 | Five groups. Runs the classification batch and caches it. |
| `POST /api/classify` | FR-02 | Batch. Takes bodies, so the eval set need not be a mailbox. |
| `POST /api/summarise` | FR-01 | 2–3 sentences, enforced in Python. Cached per email id. |
| `POST /api/draft` | FR-03 | Returns text only. **No send endpoint exists.** |
| `POST /api/voice/intent` | FR-05 | `summarise` / `read` / `draft` / `unknown`. |

Failure codes: `400` malformed request, `404` unknown email id, `422` nothing
left to summarise after preprocessing, `429` session request cap spent, `502`
the model would not produce valid output after a retry, `503` the AI service or
mailbox is unreachable. No route returns a success shape on failure.

### Two deliberate deviations from the written contract

Both are additive; neither changes a documented field.

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

The app reads a mailbox on disk. `backend/mailserver.py` is a small SMTP server
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
python -m pytest tests/ -q     # 208 passed, 1 skipped
```

The skip is deliberate and is the FR-05 accuracy criterion, which needs the real
model. It is skipped rather than stubbed because a stubbed accuracy figure would
measure the stub. Run it for real with:

```bash
python -m eval.intent_harness              # full report, exits non-zero below 90%
RUN_LLM_EVAL=1 python -m pytest tests/test_voice_intent.py
```

What the suite covers, and what it does not:

- **Real behaviour, no stub anywhere near it:** preprocessing (reply chains,
  forwarded chains, HTML, signatures, truncation), grounding (fabricated
  numbers, times, days and names flagged; paraphrase and format differences
  not), evidence verification, voice target resolution, the architecture rules,
  and the log inspection test, which runs a full session against a real log file
  on disk and greps it.
- **Stubbed model, asserting on backend behaviour:** that a fabricated evidence
  span routes to Review, that a 1- or 4-sentence summary is retried once and
  then fails loudly, that the retry is charged to the session cap. The
  assertions are about what the backend does with a given response, never about
  what a model produces.
- **Not covered:** anything in the browser. There are no frontend tests for the
  Approve control, capability detection or TTS because none of those are built.

## Evaluation

- `eval/data/voice_intents.csv` - the 30 graded transcripts for FR-05.
- `eval/data/voice_intents_unknown.csv` - out-of-scope probes that must return
  `unknown`. Not part of the graded 30.
- `eval/intent_harness.py` - runs the classifier over both and prints accuracy
  and a confusion table.
- `grounding.groundedness_rate(outputs)` - section 4.6. Takes any batch of
  recorded `/api/summarise` or `/api/draft` responses and returns the percentage
  with zero ungrounded flags, plus which entity backend produced them.

**For the report:** ROUGE measures n-gram overlap with a reference summary. It
cannot detect hallucination - a fluent, fully fabricated summary can score well.
If ROUGE is reported for FR-01 it must appear alongside the groundedness rate
and be explicitly caveated. Note also that the groundedness check is a string
check, not a semantic one: no flags means "nothing detectable is missing from
the source", not "the summary is true".

## Layout

```
frontend/src/
  api/         single fetch client -- attaches the JWT, handles every 401
  components/  shared UI
  views/       Login, Inbox, Draft, Settings
  hooks/       useAuth (useSpeech arrives in step 7)
  lib/         constants, placeholder fixtures
backend/
  app.py       application factory
  config.py    every setting, environment-driven
  routes/      auth, health, inbox, ai (summarise/classify/draft), voice
  orchestrator/  ALL LLM calls live here
    client.py      the only module that imports the OpenAI SDK
    schemas.py     JSON schemas; the category enum lives here
    prompts.py     all prompt text
    preprocess.py  quoting, signatures, HTML, truncation (section 4.2)
    grounding.py   evidence and entity verification (sections 4.3-4.6)
    classify.py    FR-02      summarise.py  FR-01
    draft.py       FR-03      intent.py     FR-05
    cache.py       summaries and labels only, never bodies
    budget.py      per-session request cap
  adapters/    email source, header parsing, fixture mailbox
  middleware/  jwt guard, log redaction
eval/          labelled data (DR-01) and the intent harness
tests/
```

## Security and safety notes

- **NFR-04.** Auth is a single fail-closed `before_request` guard, not per-route
  decorators. Everything under `/api` requires a token unless it is on an
  explicit two-entry allowlist. Forgetting to allowlist a new route makes it
  return 401 - visible and safe - rather than shipping it unauthenticated.
  `tests/test_auth.py` enumerates the URL map, so a route added later is
  covered automatically; it currently checks five protected routes.
- **No user enumeration.** Unknown email and wrong password return an identical
  body and status, and a decoy hash is verified on the unknown-email path so
  both branches take the same time.
- **NFR-03.** The JWT lives in a JS module variable, never `localStorage`.
  Server-side, bodies are fetched per request, preprocessed in memory and
  dropped; the cache holds summaries and labels only; the orchestrator logs
  character counts rather than content; and route error handlers log exception
  *frames* without exception messages, because a parse error raised mid-body
  carries the fragment it choked on. A redaction filter is the backstop.
  `tests/test_no_body_in_logs.py` runs a full session and greps a real log file.
- **Rule 4.** The OpenAI SDK is imported in exactly one file
  (`orchestrator/client.py`) and no model name appears outside `config.py`.
  Both are asserted in `tests/test_api_contract.py`.
- **Rule 5.** Sender, recipient, subject, timestamp, message id and thread id
  are parsed from headers in `adapters/headers.py`. The model is asked only for
  `category`, `category_confidence`, summaries, drafts and intent.
- **Budget.** The per-session cap is a guard rail against a runaway retry loop,
  not a billing control: it is in-process, resets on restart and is not shared
  between workers. Real spend limits belong in the OpenAI dashboard.
