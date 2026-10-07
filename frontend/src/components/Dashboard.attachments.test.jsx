/**
 * Attachments in the UI: listed, never opened.
 *
 * The backend reads an attachment's name, type and size and nothing else, so
 * the UI has nothing it could open. These tests hold it to that: a paperclip
 * in the list, names and sizes in the reading pane, and no link or button that
 * would suggest the file can be fetched.
 */

import { render, screen, within } from "@testing-library/react";
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

const WITH_ATTACHMENTS = {
  id: "email-1",
  sender_name: "Grace Hopper",
  sender: "grace@example.org",
  subject: "Assignment brief",
  snippet: "The brief and rubric are attached.",
  category: "Studies",
  received_at: "2026-09-02T09:30:00+10:00",
  unread: true,
  attachments: [
    { filename: "brief.pdf", content_type: "application/pdf", size: 5009 },
    { filename: "", content_type: "message/rfc822", size: 2048 },
  ],
};

const WITHOUT = {
  id: "email-2",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  snippet: "Can we reschedule our Thursday meeting",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
  unread: false,
  attachments: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  api.fetchInbox.mockResolvedValue({ groups: { Studies: [WITH_ATTACHMENTS], Work: [WITHOUT] } });
  api.getEmail.mockImplementation(async (id) => ({
    ...(id === WITH_ATTACHMENTS.id ? WITH_ATTACHMENTS : WITHOUT),
    body: "The brief and rubric are attached.",
  }));
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
}

describe("the inbox list", () => {
  it("marks an email that has attachments, with a count a screen reader can hear", async () => {
    renderDashboard();
    const row = await screen.findByRole("button", { name: /assignment brief/i });
    expect(within(row).getByRole("img", { name: "2 attachments" })).toBeInTheDocument();
  });

  it("does not mark an email without them", async () => {
    renderDashboard();
    const row = await screen.findByRole("button", { name: /project deadline moved to friday/i });
    expect(within(row).queryByRole("img", { name: /attachment/i })).toBeNull();
  });
});

describe("the reading pane", () => {
  async function openBrief() {
    const user = userEvent.setup();
    renderDashboard();
    await user.click(await screen.findByRole("button", { name: /assignment brief/i }));
    return screen.findByRole("list", { name: "2 attachments" });
  }

  it("lists each attachment by name and size", async () => {
    const list = await openBrief();
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("brief.pdf");
    expect(items[0]).toHaveTextContent("4.9 KB");
    expect(items[1]).toHaveTextContent("Forwarded message");
    expect(items[1]).toHaveTextContent("2 KB");
  });

  it("offers nothing to click, because no attachment content is ever fetched", async () => {
    const list = await openBrief();
    expect(within(list).queryAllByRole("link")).toHaveLength(0);
    expect(within(list).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText(/not opened or sent to the AI/i)).toBeInTheDocument();
  });

  it("shows no attachment section for an email without attachments", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await user.click(await screen.findByRole("button", { name: /project deadline moved to friday/i }));
    await screen.findByText(/the brief and rubric are attached\./i, { selector: "span" });
    expect(screen.queryByRole("list", { name: /attachment/i })).toBeNull();
  });
});
