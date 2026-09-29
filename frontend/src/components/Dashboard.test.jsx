/**
 * SR-01 at the shell level, in a browser with no speech at all.
 *
 * jsdom implements neither speechSynthesis nor SpeechRecognition, so this is
 * Firefox or Safari without any mocking: lib/capabilities.js reads the real
 * window and reports both as missing.
 *
 * The requirement is graceful degradation, and it has two halves that are easy
 * to get half-right. The notice must appear, and the controls that cannot work
 * must be gone rather than present and dead. A sidebar entry that leads to a
 * view saying "your browser cannot do this" is the failure mode this guards
 * against.
 *
 * Everything the app can do must still be reachable by clicking, so the test
 * does not stop at counting missing buttons -- it opens an email and uses the
 * AI tools.
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

const USER = { email: "student@monash.edu" };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();   // usePreference remembers the voice toggle
  api.fetchInbox.mockResolvedValue({ groups: { Work: [EMAIL] } });
  api.getEmail.mockResolvedValue({ ...EMAIL, body: "The deadline has moved to Friday." });
});

function renderDashboard() {
  return render(<Dashboard user={USER} onLogout={vi.fn()} />);
}

/** Waits for the inbox round trip so assertions run against a settled shell. */
function inboxLoaded() {
  return screen.findByRole("button", { name: /project deadline moved to friday/i });
}

describe("SR-01: a browser without speech", () => {
  it("shows the capability notice", async () => {
    renderDashboard();

    const notice = await screen.findByRole("status");
    expect(notice).toBeVisible();
    expect(notice).toHaveTextContent(/voice/i);
    // The point of the notice is that nothing is lost, so it has to say so.
    expect(notice).toHaveTextContent(/clicking/i);
  });

  it("removes the Voice Commands destination instead of leaving a dead end", async () => {
    renderDashboard();
    await inboxLoaded();

    expect(screen.queryByRole("button", { name: /voice commands/i })).toBeNull();
  });

  it("still offers the Inbox destination", async () => {
    renderDashboard();
    await inboxLoaded();

    expect(screen.getByRole("button", { name: /inbox 1/i })).toBeEnabled();
  });
});

describe("SR-01: every feature remains usable by clicking", () => {
  it("an email can be opened and summarised with the mouse alone", async () => {
    const user = userEvent.setup();
    api.summarise.mockResolvedValue({
      email_id: EMAIL.id, summary: ["The deadline is now Friday."],
      action_items: [], grounded: true, ungrounded_flags: [],
    });
    renderDashboard();

    await user.click(await screen.findByRole("button", { name: /project deadline moved to friday/i }));
    await user.click(await screen.findByRole("button", { name: /^summarise$/i }));

    expect(await screen.findByText("The deadline is now Friday.")).toBeVisible();
  });

  it("the open message offers Summarise and Draft Reply but not Read Aloud", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(await screen.findByRole("button", { name: /project deadline moved to friday/i }));

    expect(await screen.findByRole("button", { name: /^summarise$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /draft reply/i })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /read aloud/i })).toBeNull();
  });
});
