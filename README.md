# Intelligent Email Assistant

FIT3164 · Group DS-25 · Project 10

An LLM-powered email assistant: summarisation, categorisation, human-in-the-loop
reply drafting, and voice interaction. React SPA → Flask REST API → LLM
orchestrator → OpenAI API.

## Build status

Implemented against the build spec, in order. **Steps 3–10 are not built yet.**

| Step | Scope | Status |
|---|---|---|
| 1 | Frontend audit and gap table | Done |
| 2 | JWT middleware + login end to end (NFR-04) | Done |
| 3 | Orchestrator skeleton | Not started |
| 4 | `/classify`, grouped inbox, Review bucket (FR-02, FR-08) | Not started |
| 5 | `/summarise` + grounding flags (FR-01) | Not started |
| 6 | `/draft` + Approve control (FR-03) | Not started |
| 7 | Capability detection (SR-01) | Not started |
| 8 | TTS Read Aloud (FR-04) | Not started |
| 9 | STT + intent + harness (FR-05) | Not started |
| 10 | Latency instrumentation, `/api/metrics` (NFR-01) | Not started |

The inbox currently renders **placeholder fixtures** from
`frontend/src/lib/mockEmails.js`, and the AI action buttons show a "not
functional yet" toast. Neither is a real feature; both are replaced in steps 4+.

Out of scope for this build: FR-06 (tone adjustment), FR-07 (translation).

## Setup

Requires Python 3.12+ and Node 20+.

### Backend

```bash
python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

Fill in `backend/.env`:

```bash
# a long random string
python -c "import secrets; print(secrets.token_urlsafe(48))"

# then add an account (prints a JSON fragment for AUTH_USERS)
python -m backend.scripts.hash_password
```

Run it:

```bash
python -m backend.run          # http://localhost:5000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

The Vite dev server proxies `/api` to Flask, so the browser sees one origin and
no API base URL is hardcoded.

### Tests

```bash
python -m pytest tests/ -q
```

## Configuration

Everything is environment-driven; nothing is hardcoded. See
`backend/.env.example` for the full list: model name, API key, temperature, API
version, timeout, request cap, token budget, confidence threshold, latency
target, CORS origins.

`backend/.env` is gitignored. Never commit it.

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
  routes/      auth, health
  orchestrator/  ALL LLM calls live here (step 3)
  adapters/    email source, header parsing (step 4)
  middleware/  jwt guard, log redaction
eval/          labelled dataset (DR-01) and notebook (DR-02)
tests/
```

## Security notes

- **NFR-04.** Auth is a single fail-closed `before_request` guard, not per-route
  decorators. Everything under `/api` requires a token unless it is on an
  explicit two-entry allowlist. Forgetting to allowlist a new route makes it
  return 401 — visible and safe — rather than shipping it unauthenticated.
- **No user enumeration.** Unknown email and wrong password return an identical
  body and status, and a decoy hash is verified on the unknown-email path so
  both branches take the same time.
- **NFR-03.** The JWT lives in a JS module variable, never `localStorage`. It
  does not survive a page reload, which is intended. Server-side, a log filter
  redacts body-shaped fields as a backstop.
