/**
 * The single fetch client for the whole app.
 *
 * Every request goes through here, which is what makes two spec requirements
 * enforceable in one place rather than at dozens of call sites:
 *
 *  - NFR-04: the JWT is attached automatically to every request.
 *  - Section 5.1: a 401 from *any* call clears auth state and returns the user
 *    to login.
 *
 * The token is held in a module-level variable, never in localStorage or
 * sessionStorage. It therefore does not survive a page reload -- that is the
 * intended trade-off (section 5.1), not an oversight.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

let authToken = null;
let unauthorizedHandler = null;

export function setToken(token) {
  authToken = token;
}

export function clearToken() {
  authToken = null;
}

export function hasToken() {
  return authToken !== null;
}

/** Registered by useAuth so a 401 anywhere can route back to login. */
export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  constructor(message, status, options) {
    super(message, options);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, { method = "GET", body, signal, isAuthAttempt = false } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (authToken) headers.Authorization = `Bearer ${authToken}`;

  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    // fetch only rejects on network failure, not on HTTP error status.
    throw new ApiError("Could not reach the server. Is the backend running?", 0, { cause });
  }

  // A 401 means two different things depending on where it came from, and
  // conflating them told users their session had expired when they had simply
  // mistyped a password. On a sign-in attempt, 401 is "those credentials are
  // wrong" and must fall through so the server's own message reaches the form.
  // Anywhere else, 401 means the token is gone or expired: drop it and bounce
  // back to login (section 5.1).
  if (response.status === 401 && !isAuthAttempt) {
    clearToken();
    if (unauthorizedHandler) unauthorizedHandler();
    throw new ApiError("Your session has ended. Please sign in again.", 401);
  }

  let payload = null;
  if (response.status !== 204) {
    payload = await response.json().catch(() => null);
  }

  if (!response.ok) {
    // The dev server proxies /api to Flask. When Flask is not running, the
    // proxy itself answers with a 5xx and a non-JSON body -- which read as
    // "Request failed (500)" and sent us hunting for a server bug that did not
    // exist. A real backend error always carries a JSON { error } payload, so
    // the absence of one on a 5xx means the API was never reached.
    if (response.status >= 500 && payload === null) {
      throw new ApiError(
        "Cannot reach the API server. Start the backend with: python -m backend.run",
        response.status
      );
    }
    throw new ApiError(payload?.error || `Request failed (${response.status})`, response.status);
  }

  return payload;
}

/* ---------------------------------------------------------------- endpoints */

/** POST /api/auth/login -> { token, expires_in } */
export async function login(email, password) {
  return request("/api/auth/login", {
    method: "POST",
    body: { email: email.trim(), password },
    isAuthAttempt: true,
  });
}

/** GET /api/inbox -> { groups: { Work: [...], ..., Review: [...] } } (FR-08) */
export async function fetchInbox({ signal } = {}) {
  return request("/api/inbox", { signal });
}

/** POST /api/summarise -> { email_id, summary[], action_items[], grounded, ungrounded_flags[] } (FR-01) */
export async function summarise(emailId, { signal } = {}) {
  return request("/api/summarise", { method: "POST", body: { email_id: emailId }, signal });
}

/**
 * POST /api/classify -> { results: [{ id, category, confidence, ... }] } (FR-02)
 *
 * Batch by design: one round trip for the inbox, not one per row (NFR-01).
 * Each entry needs { id, subject, body }.
 */
export async function classify(emails, { signal } = {}) {
  return request("/api/classify", { method: "POST", body: { emails }, signal });
}

/**
 * POST /api/draft -> { draft, grounded, ungrounded_flags[] } (FR-03)
 *
 * Returns text and nothing else. There is no send endpoint on the backend and
 * this client deliberately does not invent one: approving a draft is a separate
 * user action, never a side effect of generating it.
 */
export async function draft(emailId, instruction, { signal } = {}) {
  const body = { email_id: emailId };
  if (instruction && instruction.trim()) body.instruction = instruction.trim();
  return request("/api/draft", { method: "POST", body, signal });
}

/**
 * POST /api/voice/intent -> { intent, target_email_id, confidence } (FR-05)
 *
 * `intent` is one of summarise | read | draft | unknown. The audio never leaves
 * the browser: recognition happens client-side and only the transcript is sent.
 *
 * `emails` is optional context ({ id, sender_name, subject }) that lets the
 * backend resolve "the one from Sarah" onto a real id deterministically.
 */
export async function voiceIntent(transcript, emails = [], alternatives = [], { signal } = {}) {
  return request("/api/voice/intent", {
    method: "POST",
    body: { transcript, emails, alternatives },
    signal,
  });
}

/** GET /api/inbox/:id -> the message with its preprocessed body.
 *
 * The list endpoint returns snippets only, so the reading pane needs this to
 * render a message. The body is fetched per request and never persisted.
 */
export async function getEmail(emailId, { signal } = {}) {
  return request(`/api/inbox/${encodeURIComponent(emailId)}`, { signal });
}

export { request };
