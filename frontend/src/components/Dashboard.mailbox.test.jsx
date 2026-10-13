/**
 * Whose mailbox is on screen. A new account starts on the demo inbox. The
 * inbox looks the same whichever mailbox it is showing: it carries no notice
 * about that. Settings is where the app says which mailbox this is, and where
 * Gmail is connected and disconnected.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "./Dashboard.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  fetchInbox: vi.fn(),
  getEmail: vi.fn(),
  summarise: vi.fn(),
  draft: vi.fn(),
  gmailStatus: vi.fn(),
  gmailConnect: vi.fn(),
  gmailDisconnect: vi.fn(),
}));

const EMAIL = {
  id: "email-1",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  snippet: "Can we reschedule our Thursday meeting",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
  unread: true,
};

const DEMO = { kind: "demo", address: null, own: false };
const OWN = { kind: "gmail", address: "me@gmail.com", own: true };
const NOT_CONNECTED = { available: true, connected: false, address: null, connected_at: null };
const CONNECTED = { available: true, connected: true, address: "me@gmail.com", connected_at: null };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  api.fetchInbox.mockResolvedValue({ groups: { Work: [EMAIL] }, mailbox: DEMO });
  api.gmailStatus.mockResolvedValue(NOT_CONNECTED);
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "new.user@example.com" }} onLogout={vi.fn()} />);
}

function inboxLoaded() {
  return screen.findByRole("button", { name: /project deadline moved to friday/i });
}

describe("the inbox", () => {
  it.each([
    ["the demo mailbox", DEMO],
    ["the user's own Gmail", OWN],
  ])("carries no notice about whose mail it is, on %s", async (_name, mailbox) => {
    api.fetchInbox.mockResolvedValue({ groups: { Work: [EMAIL] }, mailbox });
    renderDashboard();
    await inboxLoaded();

    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.queryByText(/demo inbox/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /connect gmail/i })).toBeNull();
  });
});

describe("connecting Gmail", () => {
  it("is offered in Settings to an account still on the demo mailbox", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: /^settings$/i }));

    expect(await screen.findByRole("heading", { name: /email account/i })).toBeVisible();
    expect(await screen.findByRole("button", { name: /connect gmail/i })).toBeEnabled();
  });
});

describe("changing mailbox", () => {
  it("reloads the inbox when Gmail is disconnected", async () => {
    const user = userEvent.setup();
    api.fetchInbox.mockResolvedValue({ groups: { Work: [EMAIL] }, mailbox: OWN });
    api.gmailStatus.mockResolvedValueOnce(CONNECTED).mockResolvedValue(NOT_CONNECTED);
    api.gmailDisconnect.mockResolvedValue({ connected: false, revoked: true });
    renderDashboard();
    await inboxLoaded();
    expect(api.fetchInbox).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /^settings$/i }));
    await user.click(await screen.findByRole("button", { name: /disconnect/i }));

    expect(api.gmailDisconnect).toHaveBeenCalledTimes(1);
    expect(api.fetchInbox).toHaveBeenCalledTimes(2);
  });
});
