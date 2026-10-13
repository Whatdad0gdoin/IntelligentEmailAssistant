/**
 * The command bar's example commands.
 *
 * Under the field the bar shows one row: what it is doing or has just done,
 * or, when it has nothing to say, a few commands to try. What is held to here:
 *
 *  - An example goes into the field and runs nothing, like a spoken command.
 *    It is a suggestion, and the email it would act on is the user's.
 *  - Only commands the intent route can resolve are suggested, and reading
 *    aloud only where the browser can speak.
 *  - The row belongs to the status line whenever that has something to say.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommandBar, { EXAMPLES, LISTENING_HINT, READ_EXAMPLE } from "./CommandBar.jsx";
import { ACTION_LABEL } from "./IntentChoice.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({ voiceIntent: vi.fn() }));

const EMAILS = [
  { apiId: "new", from: "Dr Helen Marsh", subject: "Assignment 2 feedback", receivedAt: "2026-09-04T19:26:00+10:00" },
  { apiId: "old", from: "David Robinson", subject: "Project deadline moved to Friday", receivedAt: "2026-08-25T09:24:00+10:00" },
];

let recognisers = [];

class FakeRecognition {
  constructor() { recognisers.push(this); }
  start() {}
  stop() {}
  abort() {}
}

beforeEach(() => {
  vi.clearAllMocks();
  recognisers = [];
});

afterEach(() => {
  delete window.webkitSpeechRecognition;
});

function renderBar(props = {}) {
  const onRun = vi.fn(() => true);
  const view = render(<CommandBar emails={EMAILS} onRun={onRun} {...props} />);
  return { onRun, ...view };
}

const field = () => screen.getByRole("textbox", { name: /command/i });
const examples = () => screen.queryByRole("group", { name: "Example commands" });
const offered = () => within(examples()).getAllByRole("button").map((b) => b.textContent);

describe("which examples are offered", () => {
  it("offers commands that name the latest email, so they work with nothing open", () => {
    renderBar();

    expect(offered()).toEqual(EXAMPLES);
    for (const example of EXAMPLES) expect(example).toMatch(/the latest email/i);
  });

  it("offers reading aloud only where the browser can speak", () => {
    const { unmount } = renderBar();
    expect(offered()).not.toContain(READ_EXAMPLE);
    unmount();

    renderBar({ readAloud: true });
    expect(offered()).toContain(READ_EXAMPLE);
  });

  it("suggests only the actions the intent route knows", () => {
    // Translate is a button on the reading pane, not a command: an example
    // for it would end in "I couldn't tell what you wanted".
    const verbs = { summarise: /^summarise/i, read: /^read/i, draft: /^draft/i };
    expect(Object.keys(verbs).sort()).toEqual(Object.keys(ACTION_LABEL).sort());
    for (const example of [...EXAMPLES, READ_EXAMPLE]) {
      expect(Object.values(verbs).some((verb) => verb.test(example)), example).toBe(true);
    }
  });

  it("offers none while there is no email to name", () => {
    renderBar({ emails: [] });

    expect(examples()).toBeNull();
    expect(field()).toBeEnabled();
  });
});

describe("choosing one", () => {
  it("fills the field, moves focus to it, and runs nothing", async () => {
    const user = userEvent.setup();
    const { onRun } = renderBar();

    await user.click(screen.getByRole("button", { name: EXAMPLES[0] }));

    expect(field()).toHaveValue(EXAMPLES[0]);
    expect(field()).toHaveFocus();
    expect(api.voiceIntent).not.toHaveBeenCalled();
    expect(onRun).not.toHaveBeenCalled();
  });

  it("replaces what was typed, and can be changed before it is run", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "draft", target_email_id: "new", confidence: 0.9 });
    const { onRun } = renderBar();
    await user.type(field(), "half a thought");

    await user.click(screen.getByRole("button", { name: EXAMPLES[1] }));
    await user.type(field(), ", briefly{Enter}");

    await waitFor(() => expect(onRun).toHaveBeenCalledWith("draft", "new"));
    expect(api.voiceIntent.mock.calls[0][0]).toBe(`${EXAMPLES[1]}, briefly`);
  });

  it("goes as a typed command: no recogniser guesses are sent with it", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "new", confidence: 0.9 });
    renderBar();

    await user.click(screen.getByRole("button", { name: EXAMPLES[0] }));
    await user.keyboard("{Enter}");      // focus is already in the field

    await waitFor(() => expect(api.voiceIntent).toHaveBeenCalledTimes(1));
    expect(api.voiceIntent.mock.calls[0]).toHaveLength(2);
    expect(api.voiceIntent.mock.calls[0][0]).toBe(EXAMPLES[0]);
  });
});

describe("the row under the field", () => {
  it("is the status line once a command has run, and the examples again on typing", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "old", confidence: 0.9 });
    renderBar();

    await user.type(field(), "summarise the email from David{Enter}");

    expect(await screen.findByText("Opened “Project deadline moved to Friday”.")).toBeInTheDocument();
    expect(examples()).toBeNull();

    await user.type(field(), "d");
    expect(examples()).not.toBeNull();
  });

  it("is the listening notice while the microphone is open, and the examples after", async () => {
    window.webkitSpeechRecognition = FakeRecognition;
    const user = userEvent.setup();
    renderBar({ voice: true });
    expect(examples()).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Speak a command" }));

    expect(screen.getByText(LISTENING_HINT)).toBeInTheDocument();
    expect(examples()).toBeNull();
    // The field says so too, beside the bars; the bars are decoration.
    expect(field()).toHaveAttribute("placeholder", "Listening…");

    act(() => recognisers.at(-1).onend());

    expect(examples()).not.toBeNull();
    expect(field()).toHaveAttribute("placeholder", expect.stringMatching(/type or say a command/i));
  });
});
