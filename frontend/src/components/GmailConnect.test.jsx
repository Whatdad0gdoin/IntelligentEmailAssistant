/**
 * Connect Gmail in Settings: the popup, the wait for Google, and what the
 * panel says in each state. The backend half (state, cookie, encrypted token)
 * is tests/test_gmail_connect.py.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GmailConnect from "./GmailConnect.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  gmailStatus: vi.fn(),
  gmailConnect: vi.fn(),
  gmailDisconnect: vi.fn(),
}));

const NOT_CONNECTED = { available: true, connected: false, address: null, connected_at: null };
const CONNECTED = {
  available: true, connected: true, address: "me@gmail.com", connected_at: "2026-10-12T01:00:00+00:00",
};
const AUTH_URL = "https://accounts.google.com/o/oauth2/auth?state=abc";

let popup;

beforeEach(() => {
  vi.clearAllMocks();
  // shouldAdvanceTime: Testing Library waits on a zero-length setTimeout after
  // each event, which a frozen fake clock would never fire.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  popup = { location: { href: "" }, close: vi.fn() };
  vi.spyOn(window, "open").mockImplementation(() => popup);
  api.gmailConnect.mockResolvedValue({ auth_url: AUTH_URL });
});

afterEach(() => {
  vi.useRealTimers();
  window.open.mockRestore();
});

async function renderPanel() {
  const onMailboxChanged = vi.fn();
  render(<GmailConnect onMailboxChanged={onMailboxChanged} />);
  await act(async () => {});   // the first status check
  return onMailboxChanged;
}

const setupUser = () => userEvent.setup({ delay: null });
const wait = (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("before connecting", () => {
  it("says when the server is not set up for it, and offers no dead button", async () => {
    api.gmailStatus.mockResolvedValue({ ...NOT_CONNECTED, available: false });
    await renderPanel();

    expect(screen.getByText(/not set up on this server/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: /connect gmail/i })).toBeNull();
  });

  it("says the inbox is the demo one and offers Connect Gmail", async () => {
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    await renderPanel();

    expect(screen.getByText(/demo inbox/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /connect gmail/i })).toBeEnabled();
  });

  it("says what access is asked for, and the testing limits", async () => {
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    await renderPanel();

    expect(screen.getByText(/read-only/i)).toHaveTextContent(/never send, delete or change/i);
    expect(screen.getByText(/test users/i)).toHaveTextContent(/7\s+days/i);
  });
});

describe("connecting", () => {
  it("opens Google in a popup and reloads the inbox once connected", async () => {
    const user = setupUser();
    api.gmailStatus
      .mockResolvedValueOnce(NOT_CONNECTED)
      .mockResolvedValueOnce(NOT_CONNECTED)
      .mockResolvedValue(CONNECTED);
    const onMailboxChanged = await renderPanel();

    await user.click(screen.getByRole("button", { name: /connect gmail/i }));

    expect(window.open).toHaveBeenCalledWith("", "mailkit-gmail", expect.stringContaining("popup"));
    expect(popup.location.href).toBe(AUTH_URL);
    expect(screen.getByRole("status")).toHaveTextContent(/finish in the google window/i);

    await wait(2000);   // still choosing an account
    expect(onMailboxChanged).not.toHaveBeenCalled();
    await wait(2000);   // done

    expect(onMailboxChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/reading me@gmail\.com/i)).toBeVisible();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("opens the popup inside the click, before waiting on the server", async () => {
    const user = setupUser();
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /connect gmail/i }));

    // A popup opened after an await is blocked as unrequested.
    expect(window.open.mock.invocationCallOrder[0])
      .toBeLessThan(api.gmailConnect.mock.invocationCallOrder[0]);
  });

  it("turns a blocked popup into a link", async () => {
    const user = setupUser();
    window.open.mockImplementation(() => null);
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /connect gmail/i }));

    expect(screen.getByRole("link", { name: /open google sign-in/i })).toHaveAttribute("href", AUTH_URL);
  });

  it("gives up after three minutes and says so", async () => {
    const user = setupUser();
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /connect gmail/i }));
    await wait(3 * 60 * 1000 + 2000);

    expect(screen.getByRole("alert")).toHaveTextContent(/did not finish connecting/i);
    expect(screen.getByRole("button", { name: /connect gmail/i })).toBeEnabled();
  });

  it("stops asking once the user cancels", async () => {
    const user = setupUser();
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /connect gmail/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    const calls = api.gmailStatus.mock.calls.length;
    await wait(10000);

    expect(api.gmailStatus.mock.calls.length).toBe(calls);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows the server's reason and closes the empty popup when connecting cannot start", async () => {
    const user = setupUser();
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    api.gmailConnect.mockRejectedValue(new Error("Connecting Gmail is not set up on this server yet."));
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /connect gmail/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(/not set up on this server/i);
    expect(popup.close).toHaveBeenCalled();
  });
});

describe("once connected", () => {
  it("names the account and hands the inbox back to the demo mailbox on Disconnect", async () => {
    const user = setupUser();
    api.gmailStatus.mockResolvedValueOnce(CONNECTED).mockResolvedValue(NOT_CONNECTED);
    api.gmailDisconnect.mockResolvedValue({ connected: false, revoked: true });
    const onMailboxChanged = await renderPanel();

    expect(screen.getByText(/reading me@gmail\.com, read-only/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /disconnect/i }));

    expect(api.gmailDisconnect).toHaveBeenCalledTimes(1);
    expect(onMailboxChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /connect gmail/i })).toBeVisible();
  });
});

describe.skipIf(typeof BroadcastChannel === "undefined")("the popup's result", () => {
  it("shows Google's refusal without waiting for the next check", async () => {
    vi.useRealTimers();
    const user = userEvent.setup();
    api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
    render(<GmailConnect onMailboxChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: /connect gmail/i }));

    const channel = new BroadcastChannel("mailkit-gmail");
    channel.postMessage({ ok: false, title: "Gmail was not connected", detail: "Google did not allow the connection." });
    channel.close();

    expect(await screen.findByRole("alert")).toHaveTextContent(/google did not allow/i);
  });
});
