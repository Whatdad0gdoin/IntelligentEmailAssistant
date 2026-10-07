/**
 * The command bar (FR-05, typed): the command path every browser keeps.
 *
 * This file runs in bare jsdom, which has neither speechSynthesis nor
 * SpeechRecognition: Firefox, in effect, where SR-01 removes Voice Commands.
 * That is the browser the bar exists for, so it is the default here rather
 * than a case that has to be set up.
 *
 * The bar adds no interpreter of its own, and these tests hold it to that. The
 * request is the voice request (same call, same newest-first candidates), and
 * the result goes through Dashboard's runVoiceAction, so what is checked is
 * the email that actually opens and the action that actually runs in the
 * reading pane, not a callback. Section 6.3 is checked as well: below the
 * floor nothing runs until the user picks.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "./Dashboard.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  fetchInbox: vi.fn(),
  getEmail: vi.fn(),
  summarise: vi.fn(),
  draft: vi.fn(),
  voiceIntent: vi.fn(),
}));

function email(id, category, receivedAt, sender, subject) {
  return {
    id,
    sender_name: sender,
    sender: `${id}@example.org`,
    subject,
    snippet: "",
    category,
    received_at: receivedAt,
    unread: false,
  };
}

// Grouped the way the API sends them, which is not date order: the newest
// email is in Studies, near the end, and an undated one comes first.
const GROUPS = {
  Work: [
    email("work-undated", "Work", "", "Uma Undated", "Timesheet reminder"),
    email("work-old", "Work", "2026-08-25T09:24:00+10:00", "David Robinson", "Project deadline moved to Friday"),
  ],
  Personal: [email("personal-mid", "Personal", "2026-09-01T18:00:00+10:00", "Sarah Chen", "Dinner this weekend?")],
  Studies: [email("studies-new", "Studies", "2026-09-04T19:26:00+10:00", "Dr Helen Marsh", "Assignment 2 feedback")],
};

const BY_ID = Object.fromEntries(Object.values(GROUPS).flat().map((e) => [e.id, e]));

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();   // usePreference remembers the voice toggle
  api.fetchInbox.mockResolvedValue({ groups: GROUPS });
  api.getEmail.mockImplementation(async (id) => ({ ...BY_ID[id], body: `The body of ${id}.` }));
  api.summarise.mockImplementation(async (id) => ({
    email_id: id,
    summary: [`Summary of ${id}.`],
    action_items: [],
    grounded: true,
    ungrounded_flags: [],
  }));
  api.draft.mockImplementation(async (id) => ({
    draft: `Draft reply to ${id}.`,
    grounded: true,
    ungrounded_flags: [],
  }));
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
}

/** The bar's field, once the inbox has loaded and there is something to name. */
async function commandField() {
  await screen.findByRole("button", { name: /assignment 2 feedback/i });
  return screen.getByRole("textbox", { name: /command/i });
}

/** Types a command into the bar and submits it with Enter. */
async function runCommand(user, text) {
  await user.type(await commandField(), `${text}{Enter}`);
  await waitFor(() => expect(api.voiceIntent).toHaveBeenCalled());
}

/** Presses Tab until `target` has focus, as a keyboard user would. */
async function tabTo(user, target, limit = 30) {
  for (let i = 0; i < limit && document.activeElement !== target; i += 1) {
    await user.tab();
  }
  expect(target).toHaveFocus();
}

describe("the bar is always there", () => {
  it("is offered in a browser with no speech, where Voice Commands is removed", async () => {
    renderDashboard();

    expect(await commandField()).toBeEnabled();
    expect(screen.getByRole("textbox", { name: /command/i }))
      .toHaveAttribute("placeholder", expect.stringMatching(/summarise the latest email/i));
    // SR-01 is unchanged: the destination is still gone, not dead-ended.
    expect(screen.queryByRole("button", { name: /voice commands/i })).toBeNull();
  });

  it("stays when voice is switched off", async () => {
    window.localStorage.setItem("mailkit:voiceEnabled", JSON.stringify(false));
    renderDashboard();

    expect(await commandField()).toBeEnabled();
  });

  it("works from another page, and brings back the inbox with the email open", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "studies-new", confidence: 0.9 });
    renderDashboard();
    await commandField();

    await user.click(screen.getByRole("button", { name: /settings/i }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    // No inbox rows on this page, so not runCommand, which waits for one.
    await user.type(screen.getByRole("textbox", { name: /command/i }), "summarise the latest email{Enter}");

    expect(await screen.findByRole("heading", { name: "Assignment 2 feedback" })).toBeVisible();
    expect(await screen.findByText("Summary of studies-new.")).toBeVisible();
  });
});

describe("a typed command goes the way a spoken one does", () => {
  it("sends the text with the inbox newest first, each email with its date", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "studies-new", confidence: 0.9 });
    renderDashboard();

    await runCommand(user, "summarise the latest email");

    expect(api.voiceIntent).toHaveBeenCalledTimes(1);
    const [text, emails] = api.voiceIntent.mock.calls[0];
    expect(text).toBe("summarise the latest email");
    // Newest first across categories, the undated email last: the same list
    // the Voice view sends (Dashboard.voice-order.test.jsx).
    expect(emails.map((e) => e.id)).toEqual(["studies-new", "personal-mid", "work-old", "work-undated"]);
    expect(emails[0]).toEqual({
      id: "studies-new",
      sender_name: "Dr Helen Marsh",
      subject: "Assignment 2 feedback",
      received_at: "2026-09-04T19:26:00+10:00",
    });
  });

  it("opens the email it names and runs the action there", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "work-old", confidence: 0.92 });
    renderDashboard();

    await runCommand(user, "summarise the email from David");

    expect(await screen.findByRole("heading", { name: "Project deadline moved to Friday" })).toBeVisible();
    expect(await screen.findByText("Summary of work-old.")).toBeVisible();
    expect(api.summarise).toHaveBeenCalledTimes(1);
    expect(api.summarise).toHaveBeenCalledWith("work-old");
    // Done: the field is clear for the next command and says what it did.
    expect(screen.getByRole("textbox", { name: /command/i })).toHaveValue("");
    expect(screen.getByText("Opened “Project deadline moved to Friday”.")).toBeInTheDocument();
  });

  it("read falls back to a summary on screen in a browser that cannot speak", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "read", target_email_id: "personal-mid", confidence: 0.88 });
    renderDashboard();

    await runCommand(user, "read me the email from Sarah");

    expect(await screen.findByText("Summary of personal-mid.")).toBeVisible();
    expect(api.summarise).toHaveBeenCalledWith("personal-mid");
    expect(screen.queryByRole("button", { name: /read aloud/i })).toBeNull();
  });

  it("with no email named, acts on the one that is open", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: null, confidence: 0.9 });
    renderDashboard();

    await user.click(await screen.findByRole("button", { name: /dinner this weekend/i }));
    await runCommand(user, "summarise this");

    expect(await screen.findByText("Summary of personal-mid.")).toBeVisible();
    expect(api.summarise).toHaveBeenCalledWith("personal-mid");
  });

  it("with no email named and none open, asks rather than guessing", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: null, confidence: 0.9 });
    renderDashboard();

    await runCommand(user, "summarise it");

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not tell which email you meant/i);
    expect(api.summarise).not.toHaveBeenCalled();
    // The command is kept, so it can be run again once an email is open.
    expect(screen.getByRole("textbox", { name: /command/i })).toHaveValue("summarise it");
  });
});

describe("section 6.3: below the floor it asks instead of acting", () => {
  it("on unknown, shows what was typed and offers the actions, running none", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "unknown", target_email_id: null, confidence: 0.2 });
    renderDashboard();

    await runCommand(user, "what's the weather");

    const question = await screen.findByRole("group", { name: /couldn't tell what you wanted/i });
    expect(within(question).getByText("“what's the weather”")).toBeInTheDocument();
    for (const name of [/summarise it/i, /read it aloud/i, /draft a reply/i, /cancel/i]) {
      expect(within(question).getByRole("button", { name })).toBeEnabled();
    }
    expect(api.summarise).not.toHaveBeenCalled();
    expect(api.draft).not.toHaveBeenCalled();
    expect(screen.getByText("Select an email to read")).toBeInTheDocument();
  });

  it("on low confidence, asks too, and the pick runs on the email the server found", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "work-old", confidence: 0.45 });
    renderDashboard();

    await runCommand(user, "something about davids email");

    const question = await screen.findByRole("group", { name: /not confident enough/i });
    expect(question).toHaveTextContent("(45%)");
    expect(api.summarise).not.toHaveBeenCalled();

    await user.click(within(question).getByRole("button", { name: /draft a reply/i }));

    expect(await screen.findByRole("heading", { name: "Project deadline moved to Friday" })).toBeVisible();
    await waitFor(() => expect(api.draft).toHaveBeenCalledTimes(1));
    expect(api.draft.mock.calls[0][0]).toBe("work-old");
    expect(api.summarise).not.toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: /not confident enough/i })).toBeNull();
  });

  it("Cancel puts the question away and runs nothing", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "unknown", target_email_id: null, confidence: 0 });
    renderDashboard();

    await runCommand(user, "hmm");
    await user.click(await screen.findByRole("button", { name: /cancel/i }));

    expect(screen.queryByRole("group", { name: /couldn't tell/i })).toBeNull();
    const field = screen.getByRole("textbox", { name: /command/i });
    expect(field).toHaveValue("hmm");
    expect(field).toHaveFocus();
    expect(api.summarise).not.toHaveBeenCalled();
    expect(api.draft).not.toHaveBeenCalled();
  });
});

describe("what it will not send", () => {
  it("an empty or whitespace-only command makes no request", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const field = await commandField();
    const run = screen.getByRole("button", { name: /^run$/i });

    expect(run).toBeDisabled();
    await user.click(field);
    await user.keyboard("{Enter}");
    await user.type(field, "     {Enter}");

    expect(run).toBeDisabled();
    expect(api.voiceIntent).not.toHaveBeenCalled();
  });
});

describe("while it works, and when it fails", () => {
  it("shows that it is busy, and a second Enter is not a second request", async () => {
    const user = userEvent.setup();
    let answer;
    api.voiceIntent.mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    renderDashboard();
    const field = await commandField();

    await user.type(field, "summarise the latest email{Enter}");

    expect(await screen.findByText("Working out what you meant…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^run$/i })).toHaveAttribute("aria-disabled", "true");
    expect(field).toHaveAttribute("readonly");
    await user.keyboard("{Enter}");
    expect(api.voiceIntent).toHaveBeenCalledTimes(1);

    await act(async () => answer({ intent: "summarise", target_email_id: "studies-new", confidence: 0.9 }));

    expect(await screen.findByText("Summary of studies-new.")).toBeVisible();
    expect(screen.queryByText("Working out what you meant…")).toBeNull();
    expect(field).not.toHaveAttribute("readonly");
  });

  it("shows the server's error plainly and keeps the command", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockRejectedValue(new Error("Could not reach the server. Is the backend running?"));
    renderDashboard();

    await runCommand(user, "summarise the latest email");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Command failed.");
    expect(alert).toHaveTextContent("Could not reach the server. Is the backend running?");
    expect(screen.getByRole("textbox", { name: /command/i })).toHaveValue("summarise the latest email");
    expect(api.summarise).not.toHaveBeenCalled();
  });
});

describe("keyboard only", () => {
  it("can be reached, run and answered without a mouse", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "work-old", confidence: 0.4 });
    renderDashboard();
    const field = await commandField();

    await tabTo(user, field);
    await user.keyboard("summarise davids email{Enter}");
    const question = await screen.findByRole("group", { name: /not confident enough/i });

    await tabTo(user, within(question).getByRole("button", { name: /summarise it/i }));
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Summary of work-old.")).toBeVisible();
    // Back in the field, empty, ready for the next command.
    expect(field).toHaveFocus();
    expect(field).toHaveValue("");
  });

  it("Escape puts the question away and returns to the field", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "unknown", target_email_id: null, confidence: 0 });
    renderDashboard();
    const field = await commandField();

    await tabTo(user, field);
    await user.keyboard("do the thing{Enter}");
    const question = await screen.findByRole("group", { name: /couldn't tell/i });
    await tabTo(user, within(question).getByRole("button", { name: /read it aloud/i }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("group", { name: /couldn't tell/i })).toBeNull();
    expect(field).toHaveFocus();
    expect(api.summarise).not.toHaveBeenCalled();
  });
});
