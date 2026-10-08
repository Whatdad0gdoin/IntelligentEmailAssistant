/**
 * Dictating into the draft reply (speech to text, alongside FR-03).
 *
 * jsdom has no speech recogniser, so a stand-in is installed before the pane
 * renders, and every instance is recorded so a test can play the browser's
 * part: deliver interim and final results, fail, or end. What is checked is
 * what the pane does with them -- where the words go, what they do to the
 * approval, and when they must be thrown away.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReadingPane from "./ReadingPane.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  summarise: vi.fn(),
  draft: vi.fn(),
  translate: vi.fn(),
}));

const EMAIL = {
  id: "email-1",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
};

const DRAFT = { draft: "Hi David,", grounded: true, ungrounded_flags: [], tone: "neutral" };

let recognisers = [];

class FakeRecognition {
  constructor() {
    this.started = false;
    this.stopped = false;
    this.aborted = false;
    recognisers.push(this);
  }
  start() { this.started = true; }
  stop() { this.stopped = true; this.onend?.(); }
  abort() { this.aborted = true; }
}

/** The browser reporting results: [text, isFinal] pairs from index `from`. */
function hear(recognition, pairs, from = 0) {
  const results = pairs.map(([text, isFinal]) => Object.assign([{ transcript: text }], { isFinal }));
  act(() => recognition.onresult({ resultIndex: from, results }));
}

beforeEach(() => {
  recognisers = [];
  window.webkitSpeechRecognition = FakeRecognition;
});

afterEach(() => {
  delete window.webkitSpeechRecognition;
  vi.clearAllMocks();
});

async function draftOnScreen(user, props = {}) {
  api.draft.mockResolvedValue(DRAFT);
  render(<ReadingPane email={EMAIL} body="Can we meet Friday?" {...props} />);
  await user.click(screen.getByRole("button", { name: /draft reply/i }));
  return screen.findByRole("textbox", { name: /draft reply, editable/i });
}

describe("dictating into the draft", () => {
  it("listens in the language chosen in Settings, continuously", async () => {
    const user = userEvent.setup();
    await draftOnScreen(user, { speechLang: "en-GB" });
    await user.click(screen.getByRole("button", { name: "Dictate" }));

    expect(recognisers).toHaveLength(1);
    const [recognition] = recognisers;
    expect(recognition.started).toBe(true);
    expect(recognition.lang).toBe("en-GB");
    expect(recognition.continuous).toBe(true);
    expect(recognition.interimResults).toBe(true);
    expect(screen.getByRole("button", { name: "Stop dictating" })).toHaveAttribute("aria-pressed", "true");
  });

  it("adds each finished phrase to the end of the draft, with spoken punctuation", async () => {
    const user = userEvent.setup();
    const textarea = await draftOnScreen(user);
    await user.click(screen.getByRole("button", { name: "Dictate" }));

    hear(recognisers[0], [["friday at 2pm works comma thanks full stop", true]]);
    expect(textarea).toHaveValue("Hi David, friday at 2pm works, thanks.");

    hear(recognisers[0], [["new paragraph james", true]], 0);
    expect(textarea).toHaveValue("Hi David, friday at 2pm works, thanks.\n\nJames");
  });

  it("shows what it is hearing before the phrase is finished, without writing it", async () => {
    const user = userEvent.setup();
    const textarea = await draftOnScreen(user);
    await user.click(screen.getByRole("button", { name: "Dictate" }));

    hear(recognisers[0], [["friday at", false]]);
    expect(screen.getByText("“friday at”")).toBeInTheDocument();
    expect(textarea).toHaveValue("Hi David,");
  });

  it("withdraws approval: dictated words have not been reviewed", async () => {
    const user = userEvent.setup();
    await draftOnScreen(user);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("button", { name: "Approved" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Dictate" }));
    hear(recognisers[0], [["see you then", true]]);
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("stops on request and goes back to Dictate", async () => {
    const user = userEvent.setup();
    await draftOnScreen(user);
    await user.click(screen.getByRole("button", { name: "Dictate" }));
    await user.click(screen.getByRole("button", { name: "Stop dictating" }));

    expect(recognisers[0].stopped).toBe(true);
    expect(screen.getByRole("button", { name: "Dictate" })).toHaveAttribute("aria-pressed", "false");
  });

  it("says plainly when the microphone is blocked", async () => {
    const user = userEvent.setup();
    await draftOnScreen(user);
    await user.click(screen.getByRole("button", { name: "Dictate" }));
    act(() => recognisers[0].onerror({ error: "not-allowed" }));
    act(() => recognisers[0].onend());

    expect(screen.getByRole("alert")).toHaveTextContent(/microphone access was denied/i);
    expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument();
  });

  it("throws away words still arriving when the draft is regenerated", async () => {
    const user = userEvent.setup();
    const textarea = await draftOnScreen(user);
    await user.click(screen.getByRole("button", { name: "Dictate" }));
    const [recognition] = recognisers;

    api.draft.mockResolvedValue({ ...DRAFT, draft: "Hello David, a new draft." });
    // The toolbar and the draft panel both offer it; either replaces the draft.
    await user.click(screen.getAllByRole("button", { name: "Regenerate" }).at(-1));
    await waitFor(() => expect(textarea).toHaveValue("Hello David, a new draft."));

    expect(recognition.aborted).toBe(true);
    hear(recognition, [["this belonged to the old draft", true]]);
    expect(textarea).toHaveValue("Hello David, a new draft.");
  });

  it("can be reached and used from the keyboard", async () => {
    const user = userEvent.setup();
    await draftOnScreen(user);
    screen.getByRole("button", { name: "Dictate" }).focus();
    await user.keyboard("{Enter}");
    expect(recognisers).toHaveLength(1);
  });
});

describe("where dictation is not offered", () => {
  it("is absent in a browser with no speech recognition (SR-01)", async () => {
    delete window.webkitSpeechRecognition;
    const user = userEvent.setup();
    await draftOnScreen(user);
    expect(screen.queryByRole("button", { name: "Dictate" })).toBeNull();
  });

  it("is absent when voice is switched off in Settings", async () => {
    const user = userEvent.setup();
    await draftOnScreen(user, { voiceEnabled: false });
    expect(screen.queryByRole("button", { name: "Dictate" })).toBeNull();
  });
});
