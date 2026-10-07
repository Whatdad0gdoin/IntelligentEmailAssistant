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
 * capabilities.js is mocked because it reads `window` at load. Voice.jsx does
 * the same for SpeechRecognition, so a stand-in is installed with vi.hoisted,
 * ahead of the imports, and every instance is recorded.
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

async function openVoice(user) {
  await screen.findByRole("button", { name: /subject of studies-newest/i });
  await user.click(screen.getByRole("button", { name: /voice commands/i }));
}

/** Starts listening and delivers one recognised utterance. */
async function say(user, transcript) {
  await user.click(screen.getByRole("button", { name: /start listening/i }));
  const recogniser = recognisers.at(-1);
  act(() => recogniser.onresult({ results: [[{ transcript }]] }));
  await waitFor(() => expect(api.voiceIntent).toHaveBeenCalledTimes(1));
  return recogniser;
}

describe("the candidates sent with a voice command", () => {
  it("are newest first across categories, undated last, ties in inbox order", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await openVoice(user);

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
    await openVoice(user);

    await say(user, "summarise the latest email");

    const [, emails] = api.voiceIntent.mock.calls[0];
    expect(emails[0]).toEqual({
      id: "studies-newest",
      sender_name: "Dr Helen Marsh",
      subject: "Subject of studies-newest",
      received_at: "2026-09-04T19:26:00+10:00",
    });
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

    await user.click(screen.getByRole("button", { name: /voice commands/i }));
    const recogniser = await say(user, "read the latest email");
    expect(recogniser.lang).toBe("en-US");
  });

  it("falls back to en-AU when the stored choice is not one on offer", async () => {
    window.localStorage.setItem("mailkit:speechLang", JSON.stringify("xx-XX"));
    const user = userEvent.setup();
    renderDashboard();
    await openVoice(user);

    const recogniser = await say(user, "read the latest email");
    expect(recogniser.lang).toBe("en-AU");
  });

  it("is not offered while voice is switched off", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByRole("button", { name: /subject of studies-newest/i });

    await user.click(screen.getByRole("button", { name: /settings/i }));
    expect(screen.getByRole("combobox", { name: /recognition language/i })).toBeInTheDocument();

    await user.click(screen.getByRole("switch"));
    expect(screen.queryByRole("combobox", { name: /recognition language/i })).toBeNull();
  });
});
