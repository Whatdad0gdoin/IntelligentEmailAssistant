/**
 * Sign-in behaviour (NFR-04, section 5.1).
 *
 * The api client already has a test proving a 401 from the login route keeps
 * the server's own wording instead of being rewritten as "your session has
 * ended". That guarantee is only worth anything if the wording reaches the
 * screen, which is what this file checks -- the form is the other end of the
 * same path, and it is where the earlier bug was actually visible.
 *
 * Rendered with the real AuthProvider rather than a stubbed useAuth: the thing
 * worth testing is the round trip from a rejected request to a message in
 * front of the user, and a stub would skip exactly the part that broke.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Login from "./Login.jsx";
import { AuthProvider } from "../hooks/useAuth.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  login: vi.fn(),
  signup: vi.fn(),
  signupOptions: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function renderLogin() {
  return render(
    <AuthProvider>
      <Login />
    </AuthProvider>
  );
}

/** Fills the form with valid-looking input and submits it. */
async function signIn(user, password = "correct-horse") {
  await user.type(screen.getByLabelText("Email address"), "student@monash.edu");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: /log in/i }));
}

describe("a rejected sign-in", () => {
  it("shows the server's message", async () => {
    const user = userEvent.setup();
    api.login.mockRejectedValue(new Error("Invalid email or password"));
    renderLogin();

    await signIn(user, "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("does not report it as an expired session", async () => {
    // The bug this replaces: every 401 was rewritten as "your session has
    // ended", which told users to sign in again when they already were.
    const user = userEvent.setup();
    api.login.mockRejectedValue(new Error("Invalid email or password"));
    renderLogin();

    await signIn(user, "wrong");

    expect(await screen.findByRole("alert")).not.toHaveTextContent(/session/i);
  });

  it("leaves the form usable so the password can be retyped", async () => {
    const user = userEvent.setup();
    api.login.mockRejectedValue(new Error("Invalid email or password"));
    renderLogin();

    await signIn(user, "wrong");
    await screen.findByRole("alert");

    expect(screen.getByRole("button", { name: /log in/i })).toBeEnabled();
  });

  it("stores no token", async () => {
    const user = userEvent.setup();
    api.login.mockRejectedValue(new Error("Invalid email or password"));
    renderLogin();

    await signIn(user, "wrong");
    await screen.findByRole("alert");

    expect(api.setToken).not.toHaveBeenCalled();
  });

  it("surfaces an unreachable backend just as plainly", async () => {
    const user = userEvent.setup();
    api.login.mockRejectedValue(new Error("Could not reach the server. Is the backend running?"));
    renderLogin();

    await signIn(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach the server/i);
  });
});

describe("an accepted sign-in", () => {
  it("stores the token and shows no error", async () => {
    const user = userEvent.setup();
    api.login.mockResolvedValue({ token: "jwt-123", expires_in: 3600 });
    renderLogin();

    await signIn(user);

    expect(api.setToken).toHaveBeenCalledWith("jwt-123");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("what the form will send", () => {
  it("cannot be submitted without both fields", async () => {
    const user = userEvent.setup();
    renderLogin();

    expect(screen.getByRole("button", { name: /log in/i })).toBeDisabled();

    await user.type(screen.getByLabelText("Email address"), "student@monash.edu");

    expect(screen.getByRole("button", { name: /log in/i })).toBeDisabled();
  });

  it("sends nothing when Enter is pressed on an incomplete form", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Email address"), "student@monash.edu{Enter}");

    expect(api.login).not.toHaveBeenCalled();
  });
});

describe("a session that ended elsewhere", () => {
  it("says so when a 401 from any other request lands on the handler", async () => {
    renderLogin();

    // Section 5.1: the client calls this from anywhere in the app. Reaching
    // for the registered handler is the only way to reproduce that here,
    // since the request that triggers it is not made by this view.
    const onUnauthorized = api.setUnauthorizedHandler.mock.calls[0][0];
    act(() => onUnauthorized());

    expect(await screen.findByText(/your session ended/i)).toBeVisible();
  });
});


describe("creating an account", () => {
  const OPEN = { enabled: true, invite_code_required: false };

  async function openSignup(user, options = OPEN) {
    api.signupOptions.mockResolvedValue(options);
    renderLogin();
    await user.click(screen.getByRole("button", { name: /create an account/i }));
    await screen.findByRole("heading", { name: /create your account/i });
  }

  async function fill(user, { email = "new.user@example.com", password = "a-long-password", confirm = password } = {}) {
    await user.type(screen.getByLabelText("Email address"), email);
    await user.type(screen.getByLabelText(/^password/i), password);
    await user.type(screen.getByLabelText(/^confirm password/i), confirm);
  }

  it("says a new account starts on the demo inbox, and Gmail is connected from Settings", async () => {
    const user = userEvent.setup();
    await openSignup(user);

    expect(screen.getByText(/demo inbox/i)).toHaveTextContent(/connect your gmail from settings/i);
  });

  it("creates the account and signs straight in", async () => {
    const user = userEvent.setup();
    api.signup.mockResolvedValue({ token: "jwt-new", expires_in: 3600 });
    await openSignup(user);

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(api.signup).toHaveBeenCalledWith("new.user@example.com", "a-long-password", "");
    expect(api.setToken).toHaveBeenCalledWith("jwt-new");
    expect(api.login).not.toHaveBeenCalled();
  });

  it("will not submit a short password or two that differ", async () => {
    const user = userEvent.setup();
    await openSignup(user);

    await fill(user, { password: "short", confirm: "short" });
    expect(screen.getByRole("button", { name: /create account/i })).toBeDisabled();

    await user.clear(screen.getByLabelText(/^password/i));
    await user.type(screen.getByLabelText(/^password/i), "a-long-password");
    expect(screen.getByText(/do not match/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /create account/i })).toBeDisabled();

    await user.clear(screen.getByLabelText(/^confirm password/i));
    await user.type(screen.getByLabelText(/^confirm password/i), "a-long-password");
    expect(screen.getByRole("button", { name: /create account/i })).toBeEnabled();
  });

  it("asks for an invite code only when the server needs one", async () => {
    const user = userEvent.setup();
    api.signup.mockResolvedValue({ token: "jwt-new", expires_in: 3600 });
    await openSignup(user, { enabled: true, invite_code_required: true });

    await fill(user);
    expect(screen.getByRole("button", { name: /create account/i })).toBeDisabled();

    await user.type(screen.getByLabelText("Invite code"), "let-me-in");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(api.signup).toHaveBeenCalledWith("new.user@example.com", "a-long-password", "let-me-in");
  });

  it("has no invite code field when none is needed", async () => {
    const user = userEvent.setup();
    await openSignup(user);

    expect(screen.queryByLabelText("Invite code")).toBeNull();
  });

  it("shows the server's reason when the account cannot be made", async () => {
    const user = userEvent.setup();
    api.signup.mockRejectedValue(new Error("An account with this email already exists. Sign in instead."));
    await openSignup(user);

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
    expect(api.setToken).not.toHaveBeenCalled();
  });

  it("says so when sign-up is turned off, and cannot be submitted", async () => {
    const user = userEvent.setup();
    await openSignup(user, { enabled: false, invite_code_required: false });

    expect(screen.getByRole("alert")).toHaveTextContent(/turned off/i);
    await fill(user);
    expect(screen.getByRole("button", { name: /create account/i })).toBeDisabled();
  });

  it("goes back to signing in", async () => {
    const user = userEvent.setup();
    await openSignup(user);

    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(screen.getByRole("heading", { name: /sign in to your inbox/i })).toBeVisible();
    expect(screen.queryByLabelText(/^confirm password/i)).toBeNull();
  });
});
