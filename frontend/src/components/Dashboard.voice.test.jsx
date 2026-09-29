/**
 * SR-01 at the shell level, in a browser that supports voice.
 *
 * The mirror of Dashboard.test.jsx. capabilities.js is mocked for the whole
 * file because it reads `window` at module load; the real detection is what
 * Dashboard.test.jsx exercises, so what is under test here is how the shell
 * responds to the answer, not how the answer is reached.
 *
 * The third case matters as much as the first two: voice can also be switched
 * off by the user, and SR-01 says doing so costs no capability. So the test
 * turns it off and checks that what disappears is the voice destination and
 * nothing else.
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

vi.mock("../lib/capabilities.js", () => ({
  capabilities: { tts: true, stt: true },
  voiceLimitation: () => null,
}));

// Settings renders the live voice, so the hook needs a synthesiser to ask.
// Installed for the file, not per test: the pane cancels queued speech as it
// unmounts, which happens after this file's hooks have run.
vi.stubGlobal("speechSynthesis", {
  getVoices: () => [{ name: "Microsoft Aria Online (Natural)", lang: "en-AU", localService: false }],
  speak: () => {},
  cancel: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
});

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

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  api.fetchInbox.mockResolvedValue({ groups: { Work: [EMAIL] } });
  api.getEmail.mockResolvedValue({ ...EMAIL, body: "The deadline has moved to Friday." });
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
}

/** Waits for the inbox round trip so assertions run against a settled shell. */
function inboxLoaded() {
  return screen.findByRole("button", { name: /project deadline moved to friday/i });
}

describe("SR-01: a browser that supports voice", () => {
  it("shows no capability notice, because there is no limitation", async () => {
    renderDashboard();
    await inboxLoaded();

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("offers Voice Commands as a destination", async () => {
    renderDashboard();
    await inboxLoaded();

    expect(screen.getByRole("button", { name: /voice commands/i })).toBeEnabled();
  });

  it("renders the Read Aloud control on an open message", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(await inboxLoaded());

    expect(await screen.findByRole("button", { name: /read aloud/i })).toBeEnabled();
  });
});

describe("SR-01: turning voice off costs no capability", () => {
  it("removes the voice destination and leaves the rest of the app", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: /settings/i }));
    const toggle = await screen.findByRole("switch");
    expect(toggle).toBeChecked();

    await user.click(toggle);

    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("button", { name: /voice commands/i })).toBeNull();
    expect(screen.getByRole("button", { name: /inbox 1/i })).toBeEnabled();
  });

  it("leaves the AI tools on an open message intact", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: /settings/i }));
    await user.click(await screen.findByRole("switch"));
    await user.click(screen.getByRole("button", { name: /^inbox$/i }));   // breadcrumb
    await user.click(await inboxLoaded());

    expect(await screen.findByRole("button", { name: /^summarise$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /draft reply/i })).toBeEnabled();
    // Only the speaker button goes; the action it triggered is still a click.
    expect(screen.queryByRole("button", { name: /read aloud/i })).toBeNull();
  });
});
