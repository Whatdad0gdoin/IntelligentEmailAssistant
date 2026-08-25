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
