/**
 * Tests for the shared fetch client.
 *
 * The case that matters most here is the one that shipped broken: a 401 from
 * the login route means "wrong credentials", while a 401 from anywhere else
 * means "your token is gone". Treating them the same told users their session
 * had ended when they had mistyped a password.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "./client.js";

function mockFetch(status, payload) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  });
}

afterEach(() => {
  api.clearToken();
  api.setUnauthorizedHandler(null);
  vi.restoreAllMocks();
});

describe("401 handling", () => {
  it("surfaces the server's message on a failed sign-in", async () => {
    global.fetch = mockFetch(401, { error: "Invalid email or password" });

    await expect(api.login("someone@monash.edu", "wrong")).rejects.toThrow(
      "Invalid email or password"
    );
  });

  it("does NOT trigger the session-expired handler on a failed sign-in", async () => {
    global.fetch = mockFetch(401, { error: "Invalid email or password" });
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);

    await expect(api.login("someone@monash.edu", "wrong")).rejects.toThrow();

    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("DOES trigger the session-expired handler on any other 401", async () => {
    global.fetch = mockFetch(401, { error: "Not authenticated" });
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    api.setToken("stale-token");

    await expect(api.request("/api/inbox")).rejects.toThrow(/session has ended/i);

    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(api.hasToken()).toBe(false);
  });
});

describe("token attachment", () => {
  it("sends no Authorization header when signed out", async () => {
    global.fetch = mockFetch(200, {});
    await api.request("/api/inbox");

    const [, options] = global.fetch.mock.calls[0];
    expect(options.headers.Authorization).toBeUndefined();
  });

  it("attaches the bearer token once signed in", async () => {
    global.fetch = mockFetch(200, {});
    api.setToken("abc123");
    await api.request("/api/inbox");

    const [, options] = global.fetch.mock.calls[0];
    expect(options.headers.Authorization).toBe("Bearer abc123");
  });
});

describe("sign-in", () => {
  it("trims a stray space off the email but never off the password", async () => {
    global.fetch = mockFetch(200, { token: "t", expires_in: 3600 });

    await api.login("  student@monash.edu  ", "  pw with spaces  ");

    const [, options] = global.fetch.mock.calls[0];
    const sent = JSON.parse(options.body);
    expect(sent.email).toBe("student@monash.edu");
    expect(sent.password).toBe("  pw with spaces  ");
  });

  it("reports a network failure distinctly from a rejected credential", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(api.login("a@b.com", "pw")).rejects.toThrow(/could not reach the server/i);
  });
});

describe("backend not running", () => {
  it("says the API is unreachable when a 5xx carries no JSON body", async () => {
    // What Vite's proxy returns when it cannot connect to Flask.
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new SyntaxError("Unexpected token < in JSON");
      },
    });

    await expect(api.request("/api/inbox")).rejects.toThrow(/cannot reach the api server/i);
  });

  it("still surfaces a genuine backend 500 that carries a JSON error", async () => {
    global.fetch = mockFetch(500, { error: "Internal server error" });

    await expect(api.request("/api/inbox")).rejects.toThrow("Internal server error");
  });
});

describe("slow and cancelled requests", () => {
  it("a timeout says the server was slow, not that it is down", async () => {
    // The two look identical to fetch (both reject) but mean opposite things:
    // one is a dead backend, the other a backend that is still working.
    global.fetch = vi.fn((_url, options) =>
      new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
        );
      })
    );

    await expect(api.request("/api/draft", { timeoutMs: 20 })).rejects.toThrow(/took longer than/i);
  });

  it("a timed-out request reports 408, not 0", async () => {
    global.fetch = vi.fn((_url, options) =>
      new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
        );
      })
    );

    await api.request("/api/draft", { timeoutMs: 20 }).catch((err) => {
      expect(err.status).toBe(408);
    });
    expect.assertions(1);
  });

  it("a genuine network failure still says the backend may be down", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.request("/api/inbox")).rejects.toThrow(/could not reach the server/i);
  });

  it("a caller cancelling is reported as a cancellation, not a failure", async () => {
    const caller = new AbortController();
    global.fetch = vi.fn((_url, options) =>
      new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }))
        );
      })
    );

    const pending = api.request("/api/inbox", { signal: caller.signal });
    caller.abort();
    await expect(pending).rejects.toThrow(/cancelled/i);
  });

  it("a request that succeeds clears its timer rather than aborting later", async () => {
    global.fetch = mockFetch(200, { ok: true });
    await expect(api.request("/api/inbox", { timeoutMs: 50 })).resolves.toEqual({ ok: true });
    // If the timer leaked, this wait would surface an unhandled abort.
    await new Promise((r) => setTimeout(r, 80));
  });
});

describe("draft body construction", () => {
  // Regression: the toolbar was wired as onClick={runDraft}, so React passed
  // its click event as the tone. The event reached JSON.stringify, threw, and
  // the failure was reported as "could not reach the server" - which sent us
  // hunting a dead backend while the request had never been sent at all.
  const fakeClickEvent = () => {
    const target = { value: "x" };
    const event = { type: "click", target, currentTarget: target, nativeEvent: {} };
    event.nativeEvent.target = event;   // circular, like a real SyntheticEvent
    return event;
  };

  it("a click event passed as the tone is ignored, not serialised", async () => {
    global.fetch = mockFetch(200, { draft: "hi", tone: "neutral" });
    await api.draft("email-1", undefined, fakeClickEvent());

    const [, options] = global.fetch.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({ email_id: "email-1" });
  });

  it("a real tone is still sent", async () => {
    global.fetch = mockFetch(200, { draft: "hi", tone: "formal" });
    await api.draft("email-1", undefined, "formal");

    const [, options] = global.fetch.mock.calls[0];
    expect(JSON.parse(options.body).tone).toBe("formal");
  });

  it("the neutral default is omitted, matching pre-tone callers", async () => {
    global.fetch = mockFetch(200, { draft: "hi", tone: "neutral" });
    await api.draft("email-1", undefined, "neutral");

    const [, options] = global.fetch.mock.calls[0];
    expect(JSON.parse(options.body)).not.toHaveProperty("tone");
  });

  it("an unencodable body is reported as an app bug, not a server outage", async () => {
    global.fetch = vi.fn();
    const circular = {};
    circular.self = circular;

    await expect(api.request("/api/draft", { method: "POST", body: circular }))
      .rejects.toThrow(/bug in the app/i);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe("translate body construction (FR-07)", () => {
  it("sends an email id and the language for an email", async () => {
    global.fetch = mockFetch(200, { translation: "Hola", grounded: true, ungrounded_flags: [] });
    await api.translate({ emailId: "email-1", language: "Spanish" });

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/translate$/);
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ email_id: "email-1", language: "Spanish" });
  });

  it("sends the text and the language for a draft, and no email id", async () => {
    global.fetch = mockFetch(200, { translation: "Hola", grounded: true, ungrounded_flags: [] });
    await api.translate({ text: "Hi David", language: "French" });

    const [, options] = global.fetch.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual({ text: "Hi David", language: "French" });
  });

  it("surfaces the backend's refusal of a language it does not offer", async () => {
    global.fetch = mockFetch(400, { error: "'language' must be one of: English, Spanish." });
    await expect(api.translate({ emailId: "email-1", language: "Klingon" }))
      .rejects.toThrow(/must be one of/i);
  });
});
