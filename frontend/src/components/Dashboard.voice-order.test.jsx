/**
 * Voice at the shell level (FR-05): the order the candidate emails are sent
 * in, and the recognition language chosen in Settings reaching the recogniser.
 *
 * Order is not cosmetic. The backend reads the first candidate as "the latest
 * email" and keeps only the first 100. Dashboard used to flatten the inbox in
 * category order -- Work, Personal, Promotions, Studies, Review -- so "summarise
 * the latest email" resolved to the newest *Work* email. The backend's own test
 * passed a list that was already sorted, so nothing caught it; this test drives
 * the real shell and inspects what it actually sends.
 *
 * A command is spoken into the command bar, which sits above every page, so
 * these tests press its microphone, deliver an utterance, and press Run.
 *
 * capabilities.js is mocked because it reads `window` at load. jsdom has no
 * SpeechRecognition, so a stand-in is installed ahead of the tests and every
 * instance is recorded.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
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

vi.mock("../lib/capabilities.js", () => ({
  capabilities: { tts: true, stt: true },
  voiceLimitation: () => null,
}));

// Settings renders the live voice, so the hook needs a synthesiser to ask.
vi.stubGlobal("speechSynthesis", {
  getVoices: () => [{ name: "Microsoft Aria Online (Natural)", lang: "en-AU", localService: false }],
  speak: () => {},
  cancel: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
});

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

function email(id, category, receivedAt, sender) {
  return {
    id,
    sender_name: sender,
    sender: `${id}@example.org`,
    subject: `Subject of ${id}`,
    snippet: "",
    category,
    received_at: receivedAt,
    unread: false,
  };
}

const SAME_MOMENT = "2026-08-24T19:41:00+10:00";

// Groups in the order the API returns them. The newest email is in Studies,
// near the end; an undated one is first; two share a timestamp.
const GROUPS = {
  Work: [
    email("work-undated", "Work", "", "Uma Undated"),
    email("work-older", "Work", "2026-08-25T09:24:00+10:00", "David Robinson"),
  ],
  Personal: [email("personal-tie", "Personal", SAME_MOMENT, "Sarah Chen")],
  Promotions: [email("promo-tie", "Promotions", SAME_MOMENT, "TechDeals")],
  Studies: [email("studies-newest", "Studies", "2026-09-04T19:26:00+10:00", "Dr Helen Marsh")],
  Review: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  recognisers.length = 0;
  window.localStorage.clear();
  api.fetchInbox.mockResolvedValue({ groups: GROUPS });
  api.getEmail.mockResolvedValue({ body: "" });
  api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: null, confidence: 0.9 });
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
}

function inboxLoaded() {
  return screen.findByRole("button", { name: /subject of studies-newest/i });
}

/** Speaks one utterance into the command bar, then runs what was heard. */
async function say(user, transcript) {
  await user.click(screen.getByRole("button", { name: "Speak a command" }));
  const recogniser = recognisers.at(-1);
  act(() => recogniser.onresult({ results: [[{ transcript }]] }));
  expect(screen.getByRole("textbox", { name: /command/i })).toHaveValue(transcript);
  await user.click(screen.getByRole("button", { name: /^run$/i }));
  await waitFor(() => expect(api.voiceIntent).toHaveBeenCalledTimes(1));
  return recogniser;
}

describe("the candidates sent with a voice command", () => {
  it("are newest first across categories, undated last, ties in inbox order", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await say(user, "summarise the latest email");

    const [, emails] = api.voiceIntent.mock.calls[0];
    expect(emails.map((e) => e.id)).toEqual([
      "studies-newest",
      "work-older",
      "personal-tie",
      "promo-tie",
      "work-undated",
    ]);
  });

  it("carry each email's received_at, so the backend can check the order", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await say(user, "summarise the latest email");

    const [, emails] = api.voiceIntent.mock.calls[0];
    expect(emails[0]).toEqual({
      id: "studies-newest",
      sender_name: "Dr Helen Marsh",
      subject: "Subject of studies-newest",
      received_at: "2026-09-04T19:26:00+10:00",
    });
  });

  it("go with what was heard and the recogniser's guesses, as one request", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await say(user, "summarise the latest email");

    const [text, , alternatives] = api.voiceIntent.mock.calls[0];
    expect(text).toBe("summarise the latest email");
    expect(alternatives).toEqual(["summarise the latest email"]);
  });
});

describe("a spoken command runs like a typed one", () => {
  it("opens the email it names and runs the action there, once Run is pressed", async () => {
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "work-older", confidence: 0.9 });
    api.summarise.mockResolvedValue({
      email_id: "work-older", summary: ["Summary of work-older."],
      action_items: [], grounded: true, ungrounded_flags: [],
    });
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await say(user, "summarise the email from David");

    expect(await screen.findByRole("heading", { name: "Subject of work-older" })).toBeVisible();
    expect(await screen.findByText("Summary of work-older.")).toBeVisible();
    expect(api.summarise).toHaveBeenCalledWith("work-older");
  });

  it("does nothing with what was heard until Run is pressed", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: "Speak a command" }));
    act(() => recognisers.at(-1).onresult({ results: [[{ transcript: "summarise the latest email" }]] }));

    expect(screen.getByRole("textbox", { name: /command/i })).toHaveValue("summarise the latest email");
    expect(api.voiceIntent).not.toHaveBeenCalled();
    expect(api.summarise).not.toHaveBeenCalled();
    expect(screen.getByText("Select an email to read")).toBeInTheDocument();
  });
});

describe("the recognition language", () => {
  it("defaults to en-AU and follows the choice made in Settings", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByRole("button", { name: /subject of studies-newest/i });

    await user.click(screen.getByRole("button", { name: /settings/i }));
    const select = screen.getByRole("combobox", { name: /recognition language/i });
    expect(select).toHaveValue("en-AU");

    await user.selectOptions(select, "en-US");
    expect(JSON.parse(window.localStorage.getItem("mailkit:speechLang"))).toBe("en-US");

    // The command bar is above Settings too, so the microphone is right here.
    const recogniser = await say(user, "read the latest email");
    expect(recogniser.lang).toBe("en-US");
  });

  it("falls back to en-AU when the stored choice is not one on offer", async () => {
    window.localStorage.setItem("mailkit:speechLang", JSON.stringify("xx-XX"));
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    const recogniser = await say(user, "read the latest email");
    expect(recogniser.lang).toBe("en-AU");
  });

  it("is not offered while voice is switched off, and neither is the microphone", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await inboxLoaded();

    await user.click(screen.getByRole("button", { name: /settings/i }));
    expect(screen.getByRole("combobox", { name: /recognition language/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speak a command" })).toBeInTheDocument();

    await user.click(screen.getByRole("switch"));
    expect(screen.queryByRole("combobox", { name: /recognition language/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Speak a command" })).toBeNull();
    // The bar itself stays: a command can still be typed.
    expect(screen.getByRole("textbox", { name: /command/i })).toBeEnabled();
  });
});
