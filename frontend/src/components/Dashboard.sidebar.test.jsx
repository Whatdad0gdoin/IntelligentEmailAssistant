/**
 * The sidebar: categories, quick filters and the voice status card.
 *
 * The categories used to be a row of chips above the list. They are in the
 * sidebar now, with two filters that cut across them, and all of it is one
 * choice: Inbox is everything, and picking anything else narrows the list.
 * What is held to here is what a person sees after each click, in the shell,
 * not the choice of which emails pass (lib/search.test.js has that).
 *
 * Bare jsdom, so this is a browser with no speech: the voice card has to say
 * so without looking like a microphone, and still lead to Settings.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "./Dashboard.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  gmailStatus: vi.fn(),
  gmailConnect: vi.fn(),
  gmailDisconnect: vi.fn(),
  fetchInbox: vi.fn(),
  getEmail: vi.fn(),
  summarise: vi.fn(),
  draft: vi.fn(),
}));

function email(id, category, sender, subject, receivedAt, extra = {}) {
  return {
    id,
    sender_name: sender,
    sender: `${id}@example.org`,
    subject,
    snippet: "",
    category,
    received_at: receivedAt,
    unread: false,
    attachments: [],
    ...extra,
  };
}

const GROUPS = {
  Work: [
    email("work-1", "Work", "David Robinson", "Project deadline moved to Friday", "2026-08-25T09:24:00+10:00",
      { unread: true }),
    email("work-2", "Work", "Northgate Accounts", "Invoice 20417", "2026-08-26T10:00:00+10:00",
      { attachments: [{ filename: "invoice.pdf", content_type: "application/pdf", size: 5009 }] }),
  ],
  Personal: [email("personal-1", "Personal", "Sarah Chen", "Dinner this weekend?", "2026-09-01T18:00:00+10:00")],
  Studies: [
    email("studies-1", "Studies", "Dr Helen Marsh", "Assignment 2 feedback", "2026-09-04T19:26:00+10:00",
      { unread: true }),
  ],
};

const SUBJECTS = {
  deadline: /project deadline moved to friday/i,
  invoice: /invoice 20417/i,
  dinner: /dinner this weekend/i,
  feedback: /assignment 2 feedback/i,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();   // usePreference remembers the voice toggle
  api.fetchInbox.mockResolvedValue({ groups: GROUPS });
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
}

const sidebar = () => within(screen.getByRole("navigation", { name: "Mailbox" }));
const row = (subject) => screen.queryByRole("button", { name: subject });

/** The subjects of the rows on screen, by their key in SUBJECTS. */
function shown() {
  return Object.keys(SUBJECTS).filter((key) => row(SUBJECTS[key]) !== null);
}

async function loaded() {
  await screen.findByRole("button", { name: SUBJECTS.feedback });
}

describe("what the sidebar lists", () => {
  it("names all five categories with how many emails each holds", async () => {
    renderDashboard();
    await loaded();

    for (const name of [/^work 2$/i, /^personal 1$/i, /^promotions 0$/i, /^studies 1$/i, /^review 0$/i]) {
      expect(sidebar().getByRole("button", { name })).toBeEnabled();
    }
  });

  it("counts unread mail and mail with attachments across the categories", async () => {
    renderDashboard();
    await loaded();

    expect(sidebar().getByRole("button", { name: /^unread 2$/i })).toBeEnabled();
    expect(sidebar().getByRole("button", { name: /^with attachments 1$/i })).toBeEnabled();
  });

  it("shows no counts while the inbox is still loading, rather than five zeros", () => {
    api.fetchInbox.mockReturnValue(new Promise(() => {}));
    renderDashboard();

    expect(sidebar().getByRole("button", { name: /^work$/i })).toBeInTheDocument();
    expect(sidebar().getByRole("button", { name: /^unread$/i })).toBeInTheDocument();
  });

  it("starts on Inbox, with everything shown and nothing else marked", async () => {
    renderDashboard();
    await loaded();

    expect(shown()).toEqual(["deadline", "invoice", "dinner", "feedback"]);
    expect(sidebar().getByRole("button", { name: /^inbox 2$/i })).toHaveClass("active");
    expect(sidebar().queryByRole("button", { current: true })).toBeNull();
  });
});

describe("choosing what to see", () => {
  it("a category shows only its own mail, and is the one marked", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();

    await user.click(sidebar().getByRole("button", { name: /^work 2$/i }));

    expect(shown()).toEqual(["deadline", "invoice"]);
    expect(sidebar().getByRole("button", { current: true })).toHaveAccessibleName(/^work 2$/i);
    expect(sidebar().getByRole("button", { name: /^inbox 2$/i })).not.toHaveClass("active");
  });

  it("Inbox brings everything back", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();
    await user.click(sidebar().getByRole("button", { name: /^personal 1$/i }));
    expect(shown()).toEqual(["dinner"]);

    await user.click(sidebar().getByRole("button", { name: /^inbox 2$/i }));

    expect(shown()).toEqual(["deadline", "invoice", "dinner", "feedback"]);
  });

  it("Unread shows unread mail from every category, under its own heading", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();

    await user.click(sidebar().getByRole("button", { name: /^unread 2$/i }));

    expect(shown()).toEqual(["deadline", "feedback"]);
    expect(screen.getByRole("heading", { name: /^unread 2$/i })).toBeVisible();
  });

  it("With attachments shows only mail that has one", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();

    await user.click(sidebar().getByRole("button", { name: /^with attachments 1$/i }));

    expect(shown()).toEqual(["invoice"]);
  });

  it("an email stays open while the list around it is narrowed", async () => {
    const user = userEvent.setup();
    api.getEmail.mockResolvedValue({ ...GROUPS.Personal[0], body: "Are you free on Saturday?" });
    renderDashboard();
    await loaded();
    await user.click(row(SUBJECTS.dinner));
    expect(await screen.findByRole("heading", { name: "Dinner this weekend?" })).toBeVisible();

    await user.click(sidebar().getByRole("button", { name: /^work 2$/i }));

    expect(shown()).toEqual(["deadline", "invoice"]);
    expect(screen.getByRole("heading", { name: "Dinner this weekend?" })).toBeVisible();
  });
});

describe("a choice with nothing in it", () => {
  it("says so in place of a bare heading, and offers the way back", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();

    await user.click(sidebar().getByRole("button", { name: /^promotions 0$/i }));

    expect(shown()).toEqual([]);
    expect(screen.getByRole("heading", { name: "Nothing in Promotions" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: /^promotions/i })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Show all mail" }));

    expect(shown()).toEqual(["deadline", "invoice", "dinner", "feedback"]);
    expect(sidebar().getByRole("button", { name: /^inbox 2$/i })).toHaveClass("active");
  });

  it("a quick filter with nothing to show uses its own words", async () => {
    const user = userEvent.setup();
    api.fetchInbox.mockResolvedValue({ groups: { Personal: GROUPS.Personal } });
    renderDashboard();
    await screen.findByRole("button", { name: SUBJECTS.dinner });

    await user.click(sidebar().getByRole("button", { name: /^with attachments 0$/i }));

    expect(screen.getByRole("heading", { name: "No mail with attachments" })).toBeVisible();
  });

  it("an empty mailbox says so once, whatever is chosen", async () => {
    const user = userEvent.setup();
    api.fetchInbox.mockResolvedValue({ groups: {} });
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "No emails" })).toBeVisible();

    await user.click(sidebar().getByRole("button", { name: /^work 0$/i }));

    expect(screen.getByRole("heading", { name: "No emails" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: /nothing in work/i })).toBeNull();
  });
});

describe("from Settings", () => {
  it("picking a category brings the inbox back, already narrowed", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();
    await user.click(screen.getByRole("button", { name: /^settings$/i }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    // On Settings nothing in the mailbox list is the page being shown.
    expect(sidebar().getByRole("button", { name: /^inbox 2$/i })).not.toHaveClass("active");

    await user.click(sidebar().getByRole("button", { name: /^studies 1$/i }));

    expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull();
    expect(shown()).toEqual(["feedback"]);
  });
});

describe("the voice card", () => {
  it("says voice is unavailable in a browser with no speech, and opens Settings", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();

    const card = screen.getByRole("button", { name: /voice unavailable/i });
    expect(card).toHaveTextContent("Not supported in this browser");
    await user.click(card);

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
  });

  it("says off once voice is switched off", async () => {
    window.localStorage.setItem("mailkit:voiceEnabled", JSON.stringify(false));
    renderDashboard();
    await loaded();

    expect(screen.getByRole("button", { name: /voice is off/i })).toBeEnabled();
  });
});
