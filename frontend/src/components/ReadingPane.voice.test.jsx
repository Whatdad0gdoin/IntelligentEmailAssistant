/**
 * SR-01, the other half: a browser that CAN speak.
 *
 * ReadingPane.test.jsx runs in bare jsdom, which is an unsupported browser by
 * accident of what jsdom implements. This file is the supported one, and it
 * has to be a separate file because lib/capabilities.js reads `window` once at
 * module load -- by the time a test body runs, the answer is already fixed, so
 * the only honest way to test the other branch is to mock the module for the
 * whole file.
 *
 * What SR-01 actually requires is checked here: the voice control appears when
 * it can work, and it never becomes the only way to do anything. Section 6.2
 * is checked too, because it is the reason Read Aloud is wired to the summary
 * rather than to the message.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReadingPane from "./ReadingPane.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  summarise: vi.fn(),
  draft: vi.fn(),
}));

// Chrome or Edge: both halves of voice are present, so there is nothing to
// warn about and every control is live.
vi.mock("../lib/capabilities.js", () => ({
  capabilities: { tts: true, stt: true },
  voiceLimitation: () => null,
}));

const EMAIL = {
  id: "email-1",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
};

const BODY = "Confidential: the Northgate contract value is 480000 dollars.";

const SUMMARY = {
  email_id: EMAIL.id,
  summary: ["David moved the deadline to Friday.", "He asks to reschedule Thursday's meeting."],
  action_items: [],
  grounded: true,
  ungrounded_flags: [],
};

/** Everything the page has asked the browser to say. */
let spoken = [];
let cancelCalls = 0;

// Installed once, for the file, rather than per test: the hook cancels any
// queued speech when the pane unmounts, and Testing Library unmounts during
// its own cleanup after this file's afterEach has run. A stub torn down per
// test is therefore already gone when the last thing that needs it runs.
vi.stubGlobal("SpeechSynthesisUtterance", class {
  constructor(text) {
    this.text = text;
  }
});
vi.stubGlobal("speechSynthesis", {
  getVoices: () => [{ name: "Microsoft Aria Online (Natural)", lang: "en-AU", localService: false }],
  speak: (utterance) => spoken.push(utterance.text),
  cancel: () => { cancelCalls += 1; },
  addEventListener: () => {},
  removeEventListener: () => {},
});

beforeEach(() => {
  vi.clearAllMocks();
  spoken = [];
  cancelCalls = 0;
});

function renderPane(props = {}) {
  return render(<ReadingPane email={EMAIL} body={BODY} {...props} />);
}

describe("SR-01: a browser that supports speech", () => {
  it("renders the Read Aloud control", () => {
    renderPane();
    expect(screen.getByRole("button", { name: /read aloud/i })).toBeEnabled();
  });

  it("still offers the click equivalents beside it", () => {
    // The requirement is not "voice exists", it is "voice is never the only
    // way". A pane that dropped the buttons once speech worked would fail.
    renderPane();
    expect(screen.getByRole("button", { name: /^summarise$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /draft reply/i })).toBeEnabled();
  });

  it("removes only the voice control when the user turns voice off", async () => {
    renderPane({ voiceEnabled: false });

    expect(screen.queryByRole("button", { name: /read aloud/i })).toBeNull();
    expect(screen.getByRole("button", { name: /^summarise$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /draft reply/i })).toBeEnabled();
  });
});

describe("section 6.2: Read Aloud reads the summary, not the email", () => {
  it("summarises first when there is no summary yet, then speaks that", async () => {
    const user = userEvent.setup();
    api.summarise.mockResolvedValue(SUMMARY);
    renderPane();

    await user.click(screen.getByRole("button", { name: /read aloud/i }));
    await screen.findByText(SUMMARY.summary[0]);

    expect(api.summarise).toHaveBeenCalledWith(EMAIL.id);
    expect(spoken).toEqual(SUMMARY.summary);
  });

  it("never sends the raw body to the synthesiser", async () => {
    const user = userEvent.setup();
    api.summarise.mockResolvedValue(SUMMARY);
    renderPane();

    await user.click(screen.getByRole("button", { name: /read aloud/i }));
    await screen.findByText(SUMMARY.summary[0]);

    // The body carries something the summary does not. If the pane ever read
    // the message itself, this is where it would show up.
    expect(spoken.join(" ")).not.toMatch(/480000|Confidential/);
  });

  it("a second click stops rather than starting a second read", async () => {
    const user = userEvent.setup();
    api.summarise.mockResolvedValue(SUMMARY);
    renderPane();

    await user.click(screen.getByRole("button", { name: /read aloud/i }));
    const stop = await screen.findByRole("button", { name: /^stop$/i });

    const utterancesBefore = spoken.length;
    await user.click(stop);

    expect(cancelCalls).toBeGreaterThan(0);
    expect(spoken).toHaveLength(utterancesBefore);
    expect(screen.getByRole("button", { name: /read aloud/i })).toBeEnabled();
  });
});
