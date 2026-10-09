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
 * turns it off and checks that what disappears is the microphone and the
 * speaker button, and nothing else.
 *
 * A command is spoken into the command bar; there is no voice page. Settings
 * is where the app says where spoken audio goes, so that is checked here too.
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

// And a recogniser, which is what "supports voice" means for the microphone.
// The command bar looks for the constructor itself, so a mocked capability
// alone would leave it with nothing to start.
vi.stubGlobal("webkitSpeechRecognition", class {
  start() {}
  stop() {}
  abort() {}
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

  it("puts a microphone in the command bar, and no voice page in the sidebar", async () => {
    renderDashboard();
    await inboxLoaded();

    expect(screen.getByRole("button", { name: "Speak a command" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: /command/i }))
      .toHaveAttribute("placeholder", expect.stringMatching(/type or say a command/i));
    expect(screen.queryByRole("button", { name: /voice commands/i })).toBeNull();
    expect(screen.queryByText(/hands-free/i)).toBeNull();
  });

  it("keeps the microphone within reach on every page", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: /settings/i }));

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Speak a command" })).toBeEnabled();
  });

  it("renders the Read Aloud control on an open message", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(await inboxLoaded());

    expect(await screen.findByRole("button", { name: /read aloud/i })).toBeEnabled();
  });
});

describe("where the audio goes, said where voice is switched on", () => {
  async function openSettings() {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();
    await user.click(screen.getByRole("button", { name: /settings/i }));
    await screen.findByRole("heading", { name: "Settings" });
    return user;
  }

  it("says our server never receives it", async () => {
    await openSettings();
    expect(screen.getByText(/our server never receives your audio, only the text recognised from it/i))
      .toBeInTheDocument();
  });

  it("says the browser's speech service may, and names who runs it", async () => {
    await openSettings();
    expect(screen.getByText(/chrome sends it to google unless on-device\s+recognition is used/i))
      .toBeInTheDocument();
    expect(screen.getByText(/edge sends it to microsoft/i)).toBeInTheDocument();
  });

  it("does not claim the voice is processed in the browser", async () => {
    await openSettings();
    expect(screen.queryByText(/processed\s+in the browser/i)).toBeNull();
  });

  it("is not shown once voice is off: there is no microphone left to explain", async () => {
    const user = await openSettings();
    await user.click(screen.getByRole("switch"));
    expect(screen.queryByText(/our server never receives your audio/i)).toBeNull();
  });
});

describe("SR-01: turning voice off costs no capability", () => {
  it("removes the microphone and leaves the rest of the app", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: /settings/i }));
    const toggle = await screen.findByRole("switch");
    expect(toggle).toBeChecked();

    await user.click(toggle);

    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Speak a command" })).toBeNull();
    // Commands are still there, typed.
    expect(screen.getByRole("textbox", { name: /command/i })).toBeEnabled();
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
