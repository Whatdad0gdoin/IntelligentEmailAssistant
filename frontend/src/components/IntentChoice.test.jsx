/**
 * The "ask, never guess" card (FR-05, spec section 6.3), and a spoken command
 * asking through it.
 *
 * The card is one component so the spoken and the typed path cannot drift
 * apart. CommandBar.test.jsx covers the typed half; the spoken half is here,
 * driven through the command bar's microphone.
 *
 * jsdom has no SpeechRecognition, so a stand-in is installed ahead of the
 * tests and every instance is recorded.
 */

import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CommandBar from "./CommandBar.jsx";
import IntentChoice, { CONFIDENCE_FLOOR, intentCandidates, isConfident } from "./IntentChoice.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({ voiceIntent: vi.fn() }));

const recognisers = vi.hoisted(() => {
  const created = [];
  window.webkitSpeechRecognition = class {
    constructor() {
      created.push(this);
    }
    start() {}
    stop() {}
    abort() {}
  };
  return created;
});

beforeEach(() => {
  vi.clearAllMocks();
  recognisers.length = 0;
});

describe("when to ask", () => {
  it("acts at or above the floor, on an action the reading pane knows", () => {
    expect(CONFIDENCE_FLOOR).toBe(0.6);   // INTENT_CONFIDENCE_THRESHOLD in backend/.env.example
    expect(isConfident({ intent: "summarise", confidence: 0.6 })).toBe(true);
    expect(isConfident({ intent: "draft", confidence: 0.95 })).toBe(true);
  });

  it("asks below the floor, on unknown, and on anything it cannot read", () => {
    expect(isConfident({ intent: "summarise", confidence: 0.59 })).toBe(false);
    expect(isConfident({ intent: "unknown", confidence: 0.99 })).toBe(false);
    expect(isConfident({ intent: "delete", confidence: 0.99 })).toBe(false);
    expect(isConfident({ intent: "read" })).toBe(false);
    expect(isConfident(null)).toBe(false);
  });
});

describe("the candidates sent with a command", () => {
  it("are reshaped for the route and keep the order they were given", () => {
    const emails = [
      { apiId: "b", from: "Sarah Chen", subject: "Dinner", receivedAt: "2026-09-01T18:00:00+10:00" },
      { apiId: "a", from: "David Robinson", subject: "Deadline", receivedAt: "" },
    ];
    expect(intentCandidates(emails)).toEqual([
      { id: "b", sender_name: "Sarah Chen", subject: "Dinner", received_at: "2026-09-01T18:00:00+10:00" },
      { id: "a", sender_name: "David Robinson", subject: "Deadline", received_at: "" },
    ]);
  });
});

describe("the question", () => {
  const UNKNOWN = { intent: "unknown", target_email_id: null, confidence: 0.1 };

  it("says it could not tell, offers the three actions, and reports the pick", async () => {
    const user = userEvent.setup();
    const onChoose = vi.fn();
    render(<IntentChoice result={UNKNOWN} onChoose={onChoose} />);

    const group = screen.getByRole("group", { name: /couldn't tell what you wanted/i });
    expect(within(group).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["Summarise it", "Read it aloud", "Draft a reply"]);

    await user.click(within(group).getByRole("button", { name: "Read it aloud" }));
    expect(onChoose).toHaveBeenCalledWith("read");
  });

  it("gives the confidence when it understood, but not well enough", () => {
    render(<IntentChoice result={{ intent: "draft", target_email_id: "x", confidence: 0.42 }} onChoose={vi.fn()} />);
    expect(screen.getByRole("group", { name: /not confident enough to act on that \(42%\)/i })).toBeInTheDocument();
  });

  it("offers Cancel only to a caller that can cancel", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { rerender } = render(<IntentChoice result={UNKNOWN} onChoose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();

    rerender(<IntentChoice result={UNKNOWN} onChoose={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

describe("a spoken command asks through it", () => {
  const EMAILS = [{ apiId: "a", from: "David Robinson", subject: "Deadline", receivedAt: "" }];

  /** Speaks one utterance into the command bar, then runs what was heard. */
  async function say(user, transcript) {
    await user.click(screen.getByRole("button", { name: "Speak a command" }));
    act(() => recognisers.at(-1).onresult({ results: [[{ transcript }]] }));
    await user.click(screen.getByRole("button", { name: /^run$/i }));
  }

  it("below the floor, shows the choice and runs only the action picked", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn(() => true);
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "a", confidence: 0.3 });
    render(<CommandBar emails={EMAILS} onRun={onRun} voice />);

    await say(user, "summarise davids email");
    const group = await screen.findByRole("group", { name: /not confident enough/i });
    expect(onRun).not.toHaveBeenCalled();
    // The same card a typed command gets, Cancel included.
    expect(within(group).getByRole("button", { name: /cancel/i })).toBeEnabled();

    await user.click(within(group).getByRole("button", { name: "Draft a reply" }));
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith("draft", "a");
  });

  it("with no email to act on, says so instead of guessing", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "unknown", target_email_id: null, confidence: 0 });
    render(<CommandBar emails={EMAILS} onRun={() => false} voice />);

    await say(user, "do something");
    const group = await screen.findByRole("group", { name: /couldn't tell/i });
    await user.click(within(group).getByRole("button", { name: "Summarise it" }));

    expect(screen.getByText(/could not tell which email you meant/i)).toBeInTheDocument();
  });
});
