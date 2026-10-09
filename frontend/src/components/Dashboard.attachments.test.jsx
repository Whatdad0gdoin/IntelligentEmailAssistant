/**
 * Attachments in the UI: listed with the inbox, fetched only when opened.
 *
 * The inbox carries an attachment's name, type and size and nothing else.
 * These tests hold the app to that: a paperclip in the list, names and sizes
 * in the reading pane, and no request for a file until the user presses View
 * or Save on it. What View and Save then do with the file is covered in
 * Attachments.test.jsx.
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
  fetchAttachment: vi.fn(),
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

  it("fetches no attachment to show the list, and links to none", async () => {
    const list = await openBrief();
    expect(api.fetchAttachment).not.toHaveBeenCalled();
    // A link would need the token in its URL; the file is fetched instead.
    expect(within(list).queryAllByRole("link")).toHaveLength(0);
    expect(screen.getByText(/fetched only when you open or save it/i)).toBeInTheDocument();
    expect(screen.getByText(/never sent to the AI/i)).toBeInTheDocument();
  });

  it("offers Save for every attachment and View only for one the page can show", async () => {
    const list = await openBrief();
    const [pdf, forwarded] = within(list).getAllByRole("listitem");
    expect(within(pdf).getByRole("button", { name: "View brief.pdf" })).toBeInTheDocument();
    expect(within(pdf).getByRole("button", { name: "Save brief.pdf" })).toBeInTheDocument();
    expect(within(forwarded).queryByRole("button", { name: /^view/i })).toBeNull();
    expect(within(forwarded).getByRole("button", { name: "Save Forwarded message" })).toBeInTheDocument();
  });

  it("asks for an attachment by the open email and its place in the list", async () => {
    api.fetchAttachment.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
    URL.createObjectURL = vi.fn(() => "blob:mock/brief");
    URL.revokeObjectURL = vi.fn();
    const user = userEvent.setup();
    const list = await openBrief();

    await user.click(within(list).getByRole("button", { name: "View brief.pdf" }));

    expect(api.fetchAttachment).toHaveBeenCalledTimes(1);
    expect(api.fetchAttachment.mock.calls[0].slice(0, 2)).toEqual(["email-1", 0]);
    expect(await screen.findByRole("region", { name: "Preview of brief.pdf" })).toBeInTheDocument();
  });

  it("shows no attachment section for an email without attachments", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await user.click(await screen.findByRole("button", { name: /project deadline moved to friday/i }));
    await screen.findByText(/the brief and rubric are attached\./i, { selector: "span" });
    expect(screen.queryByRole("list", { name: /attachment/i })).toBeNull();
  });
});
