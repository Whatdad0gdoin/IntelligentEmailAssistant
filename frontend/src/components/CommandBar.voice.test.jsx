/**
 * Speaking a command into the command bar (FR-05, spoken).
 *
 * The bar is the only place a command is spoken; there is no voice page. What
 * is held to here:
 *
 *  - The microphone appears only where it can work (SR-01): voice switched on,
 *    and a recogniser in this browser. Never a dead button.
 *  - Speaking fills the field and runs nothing. A recogniser mishears, so what
 *    it heard is shown first and the command goes when the user presses Run.
 *  - Sent as heard, the recogniser's other guesses go too, so the backend can
 *    match a name the top guess missed. Once edited it is a typed command.
 *  - The recogniser is given the language from Settings, never the browser's
 *    menu language.
 *  - The bar says where the audio goes while it is listening.
 *
 * jsdom has no speech recogniser, so a stand-in is installed before each test
 * and every instance recorded, letting a test play the browser's part: deliver
 * a result, fail, or end. CommandBar.test.jsx covers the typed path, in a
 * browser with no speech at all.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommandBar, { HEARD_HINT, LISTENING_HINT } from "./CommandBar.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({ voiceIntent: vi.fn() }));

const EMAILS = [
  { apiId: "new", from: "Dr Helen Marsh", subject: "Assignment 2 feedback", receivedAt: "2026-09-04T19:26:00+10:00" },
  { apiId: "old", from: "David Robinson", subject: "Project deadline moved to Friday", receivedAt: "2026-08-25T09:24:00+10:00" },
];

let recognisers = [];

class FakeRecognition {
  constructor() {
    this.started = false;
    this.stopped = false;
    this.aborted = false;
    recognisers.push(this);
  }
  start() { this.started = true; }
  stop() { this.stopped = true; }
  abort() { this.aborted = true; }
}

/** The browser reporting one finished utterance, best guess first. */
function hear(recognition, ...guesses) {
  act(() => recognition.onresult({ results: [guesses.map((transcript) => ({ transcript }))] }));
}

beforeEach(() => {
  vi.clearAllMocks();
  recognisers = [];
  window.webkitSpeechRecognition = FakeRecognition;
});

afterEach(() => {
  delete window.webkitSpeechRecognition;
  vi.restoreAllMocks();
});

function renderBar(props = {}) {
  const onRun = vi.fn(() => true);
  const view = render(<CommandBar emails={EMAILS} onRun={onRun} voice {...props} />);
  return { onRun, ...view };
}

const field = () => screen.getByRole("textbox", { name: /command/i });
const mic = () => screen.getByRole("button", { name: "Speak a command" });
const runButton = () => screen.getByRole("button", { name: /^run$/i });

/** Presses the microphone and returns the recogniser it started. */
async function listen(user) {
  await user.click(mic());
  return recognisers.at(-1);
}

describe("where the microphone is offered (SR-01)", () => {
  it("is there when voice is on and the browser can recognise speech", () => {
    renderBar();
    expect(mic()).toHaveAttribute("aria-pressed", "false");
    expect(field()).toHaveAttribute("placeholder", expect.stringMatching(/type or say a command/i));
  });

  it("is not there when voice is switched off", () => {
    renderBar({ voice: false });
    expect(screen.queryByRole("button", { name: /speak a command/i })).toBeNull();
    expect(field()).toHaveAttribute("placeholder", expect.stringMatching(/^type a command/i));
  });

  it("is not there in a browser with no recogniser, even with voice on", () => {
    delete window.webkitSpeechRecognition;
    renderBar();
    expect(screen.queryByRole("button", { name: /speak a command/i })).toBeNull();
    expect(field()).toBeEnabled();      // the typed path is untouched
  });

  it("does not submit the form when pressed", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.type(field(), "summarise the latest email");

    await listen(user);

    expect(api.voiceIntent).not.toHaveBeenCalled();
  });
});

describe("listening", () => {
  it("starts one recogniser for one utterance, asking for its other guesses", async () => {
    const user = userEvent.setup();
    renderBar();

    const recognition = await listen(user);

    expect(recognisers).toHaveLength(1);
    expect(recognition.started).toBe(true);
    expect(recognition.interimResults).toBe(false);
    expect(recognition.maxAlternatives).toBe(5);
    expect(recognition.continuous).not.toBe(true);
  });

  it("uses en-AU by default, not the browser's own language", async () => {
    // navigator.language is the browser's menu language: an Indonesian Chrome
    // would hand the recogniser id-ID for a command spoken in English.
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("id-ID");
    const user = userEvent.setup();
    renderBar();

    expect((await listen(user)).lang).toBe("en-AU");
  });

  it("uses the language chosen in Settings", async () => {
    const user = userEvent.setup();
    renderBar({ speechLang: "en-IN" });

    expect((await listen(user)).lang).toBe("en-IN");
  });

  it("shows that it is listening by more than colour, and where the audio goes", async () => {
    const user = userEvent.setup();
    renderBar();

    await listen(user);

    const stop = screen.getByRole("button", { name: "Stop listening" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(LISTENING_HINT)).toBeInTheDocument();
    expect(LISTENING_HINT).toMatch(/our server never receives your audio/i);
    expect(LISTENING_HINT).toMatch(/your browser's speech service may/i);
  });

  it("pressing it again stops, and the button goes back when the browser ends", async () => {
    const user = userEvent.setup();
    renderBar();
    const recognition = await listen(user);

    await user.click(screen.getByRole("button", { name: "Stop listening" }));
    expect(recognition.stopped).toBe(true);
    act(() => recognition.onend());

    expect(mic()).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(LISTENING_HINT)).toBeNull();
    expect(recognisers).toHaveLength(1);
  });
});

describe("what was heard goes in the field, and nothing runs", () => {
  it("fills the field, moves focus to it, and sends nothing", async () => {
    const user = userEvent.setup();
    const { onRun } = renderBar();

    hear(await listen(user), "summarise the latest email");

    expect(field()).toHaveValue("summarise the latest email");
    expect(field()).toHaveFocus();
    expect(screen.getByText(HEARD_HINT)).toBeInTheDocument();
    expect(mic()).toHaveAttribute("aria-pressed", "false");
    expect(api.voiceIntent).not.toHaveBeenCalled();
    expect(onRun).not.toHaveBeenCalled();
  });

  it("replaces whatever was typed before", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.type(field(), "half a thought");

    hear(await listen(user), "draft a reply to David");

    expect(field()).toHaveValue("draft a reply to David");
  });

  it("can be corrected before it is run", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "old", confidence: 0.9 });
    const { onRun } = renderBar();
    hear(await listen(user), "summarise the email from Davide");

    await user.type(field(), "{Backspace}{Enter}");

    await waitFor(() => expect(onRun).toHaveBeenCalledWith("summarise", "old"));
    expect(api.voiceIntent.mock.calls[0][0]).toBe("summarise the email from David");
  });

  it("keeps a long utterance within what the route reads", async () => {
    const user = userEvent.setup();
    renderBar();

    hear(await listen(user), "a".repeat(700));

    expect(field().value).toHaveLength(500);
  });

  it("an utterance with nothing in it changes nothing", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.type(field(), "keep me");

    hear(await listen(user), "   ");

    expect(field()).toHaveValue("keep me");
    expect(screen.queryByText(HEARD_HINT)).toBeNull();
  });
});

describe("running what was heard", () => {
  it("sends the heard text with the recogniser's other guesses, best first", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "new", confidence: 0.9 });
    renderBar();
    hear(await listen(user), "summarise the email from helen", "summarise the email from Ellen",
         "summarise the email from helen", "summarize the e-mail from Helen");

    await user.click(runButton());

    await waitFor(() => expect(api.voiceIntent).toHaveBeenCalledTimes(1));
    const [text, candidates, alternatives] = api.voiceIntent.mock.calls[0];
    expect(text).toBe("summarise the email from helen");
    expect(candidates.map((c) => c.id)).toEqual(["new", "old"]);
    // Repeats add nothing to the match, so each guess is sent once.
    expect(alternatives).toEqual([
      "summarise the email from helen",
      "summarise the email from Ellen",
      "summarize the e-mail from Helen",
    ]);
  });

  it("an edited command is a typed one: the guesses are not sent", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "draft", target_email_id: "old", confidence: 0.9 });
    renderBar();
    hear(await listen(user), "draft a reply to dave", "draft a reply to Dave R");

    await user.type(field(), "id{Enter}");

    await waitFor(() => expect(api.voiceIntent).toHaveBeenCalledTimes(1));
    expect(api.voiceIntent.mock.calls[0]).toHaveLength(2);
    expect(api.voiceIntent.mock.calls[0][0]).toBe("draft a reply to daveid");
  });

  it("a command typed from scratch sends no guesses either", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "new", confidence: 0.9 });
    renderBar();

    await user.type(field(), "summarise the latest email{Enter}");

    await waitFor(() => expect(api.voiceIntent).toHaveBeenCalledTimes(1));
    expect(api.voiceIntent.mock.calls[0]).toHaveLength(2);
  });

  it("a confident answer runs the action on the email named, and clears the field", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "read", target_email_id: "old", confidence: 0.88 });
    const { onRun } = renderBar();
    hear(await listen(user), "read me the email from David");

    await user.keyboard("{Enter}");      // focus is already in the field

    await waitFor(() => expect(onRun).toHaveBeenCalledWith("read", "old"));
    expect(field()).toHaveValue("");
    expect(screen.getByText("Opened “Project deadline moved to Friday”.")).toBeInTheDocument();
    expect(screen.queryByText(HEARD_HINT)).toBeNull();
  });

  it("below the floor it asks, showing what was heard, and runs only the pick", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "old", confidence: 0.3 });
    const { onRun } = renderBar();
    hear(await listen(user), "something about davids email");

    await user.click(runButton());

    const question = await screen.findByRole("group", { name: /not confident enough/i });
    expect(within(question).getByText("Heard")).toBeInTheDocument();
    expect(within(question).getByText("“something about davids email”")).toBeInTheDocument();
    expect(onRun).not.toHaveBeenCalled();

    await user.click(within(question).getByRole("button", { name: "Draft a reply" }));
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith("draft", "old");
  });

  it("a typed command that is asked about is labelled as typed", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "unknown", target_email_id: null, confidence: 0 });
    renderBar();

    await user.type(field(), "do the thing{Enter}");

    const question = await screen.findByRole("group", { name: /couldn't tell/i });
    expect(within(question).getByText("You typed")).toBeInTheDocument();
    expect(within(question).queryByText("Heard")).toBeNull();
  });

  it("with no email to act on, says so and keeps what was heard", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: null, confidence: 0.9 });
    render(<CommandBar emails={EMAILS} onRun={() => false} voice />);
    hear(await listen(user), "summarise it");

    await user.click(runButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not tell which email you meant/i);
    expect(field()).toHaveValue("summarise it");
  });
});

describe("one thing at a time", () => {
  it("running a command stops listening, so a late phrase cannot overwrite it", async () => {
    const user = userEvent.setup();
    let answer;
    api.voiceIntent.mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    renderBar();
    await user.type(field(), "summarise the latest email");
    const recognition = await listen(user);

    await user.type(field(), "{Enter}");

    expect(recognition.aborted).toBe(true);
    hear(recognition, "something said too late");
    expect(field()).toHaveValue("summarise the latest email");
    await act(async () => answer({ intent: "summarise", target_email_id: "new", confidence: 0.9 }));
  });

  it("does not start listening while a command is on its way", async () => {
    const user = userEvent.setup();
    let answer;
    api.voiceIntent.mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    renderBar();
    await user.type(field(), "summarise the latest email{Enter}");
    await screen.findByText("Working out what you meant…");

    await user.click(mic());

    expect(mic()).toHaveAttribute("aria-disabled", "true");
    expect(recognisers).toHaveLength(0);
    await act(async () => answer({ intent: "summarise", target_email_id: "new", confidence: 0.9 }));
  });

  it("lets go of the microphone when the bar goes away", async () => {
    const user = userEvent.setup();
    const { unmount } = renderBar();
    const recognition = await listen(user);

    unmount();

    expect(recognition.aborted).toBe(true);
  });
});

describe("when listening fails", () => {
  async function fail(user, code) {
    const recognition = await listen(user);
    act(() => {
      recognition.onerror({ error: code });
      recognition.onend();
    });
  }

  it("a blocked microphone says so, and how to fix it", async () => {
    const user = userEvent.setup();
    renderBar();

    await fail(user, "not-allowed");

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Could not listen.");
    expect(alert).toHaveTextContent(/microphone access was denied/i);
    expect(mic()).toHaveAttribute("aria-pressed", "false");
    expect(api.voiceIntent).not.toHaveBeenCalled();
  });

  it("silence is reported as silence, not as a broken microphone", async () => {
    const user = userEvent.setup();
    renderBar();

    await fail(user, "no-speech");

    expect(screen.getByRole("alert")).toHaveTextContent(/nothing was heard/i);
  });

  it("an error it has no words for still names the browser's reason", async () => {
    const user = userEvent.setup();
    renderBar();

    await fail(user, "language-not-supported");

    expect(screen.getByRole("alert")).toHaveTextContent("Speech recognition failed (language-not-supported).");
  });

  it("stopping on purpose is not an error", async () => {
    const user = userEvent.setup();
    renderBar();

    await fail(user, "aborted");

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a recogniser that will not start says so and leaves the bar usable", async () => {
    window.webkitSpeechRecognition = class extends FakeRecognition {
      start() { throw new Error("InvalidStateError"); }
    };
    const user = userEvent.setup();
    renderBar();

    await user.click(mic());

    expect(screen.getByRole("alert")).toHaveTextContent(/listening could not start/i);
    expect(mic()).toHaveAttribute("aria-pressed", "false");
    expect(field()).toBeEnabled();
  });

  it("the message goes once the user types or tries again", async () => {
    const user = userEvent.setup();
    renderBar();
    await fail(user, "no-speech");
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await user.type(field(), "s");
    expect(screen.queryByRole("alert")).toBeNull();

    await fail(user, "no-speech");
    await listen(user);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
