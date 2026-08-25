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

export { request };
