/**
 * The inbox's layout, as far as jsdom can see it (FR-08).
 *
 * With no email open the list has the whole page. Opening one, by a click or
 * by a command, splits the page: the list comes in to its column and the
 * reading pane widens beside it. The widths and the animation are CSS, which
 * jsdom neither loads nor lays out, so they are pinned as text in
 * styles.test.js ("reader layout"). What is held to here is what that CSS
 * hangs on:
 *
 *  - the split carries `has-selection` exactly while an email is open;
 *  - the reading pane is in the page in both states, the same element, and
 *    empty until then. A pane that only mounted with the email would have no
 *    width to grow from, and the change would be a jump, not a transition;
 *  - the "Select an email to read" card is not rendered anywhere.
 *
 * Driven through Dashboard, the real shell, because that is what decides which
 * email is open: a row's click and the command bar both end in its `selected`.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "../components/Dashboard.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  gmailStatus: vi.fn(),
  gmailConnect: vi.fn(),
  gmailDisconnect: vi.fn(),
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

const GROUPS = {
  Work: [email("work-1", "Work", "2026-08-25T09:24:00+10:00", "David Robinson", "Project deadline moved to Friday")],
  Personal: [email("personal-1", "Personal", "2026-09-01T18:00:00+10:00", "Sarah Chen", "Dinner this weekend?")],
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
});

/** Renders the shell. The two elements the stylesheet lays out have no role,
 *  so they are found by the class the stylesheet itself uses. */
function renderDashboard() {
  const { container } = render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
  return {
    split: () => container.querySelector(".inbox-split"),
    list: () => container.querySelector(".inbox-left"),
    pane: () => container.querySelector(".inbox-right"),
  };
}

const row = (subject) => screen.getByRole("button", { name: subject });

function loaded() {
  return screen.findByRole("button", { name: /dinner this weekend/i });
}

/** Types a command into the bar and submits it with Enter. */
async function runCommand(user, text) {
  await user.type(screen.getByRole("textbox", { name: /command/i }), `${text}{Enter}`);
  await waitFor(() => expect(api.voiceIntent).toHaveBeenCalled());
}

describe("with no email open", () => {
  it("the list has the page: the split is unmarked and the reading pane is empty", async () => {
    const { split, list, pane } = renderDashboard();
    await loaded();

    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: /^summarise$/i })).toBeNull();
    // The mail is in the list's column, which is the one given the width.
    expect(within(list()).getByRole("button", { name: /project deadline moved to friday/i })).toBeVisible();
    expect(within(list()).getByRole("button", { name: /dinner this weekend/i })).toBeVisible();
  });

  it("nothing asks for an email to be selected", async () => {
    renderDashboard();
    await loaded();

    expect(screen.queryByText(/select an email to read/i)).toBeNull();
    expect(screen.queryByText(/choose a message to view it here/i)).toBeNull();
  });

  it("is the same while the inbox is still loading", () => {
    api.fetchInbox.mockReturnValue(new Promise(() => {}));
    const { split, pane } = renderDashboard();

    expect(screen.getByLabelText("Loading inbox")).toBeInTheDocument();
    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBeEmptyDOMElement();
    expect(screen.queryByText(/select an email to read/i)).toBeNull();
  });

  it("an empty mailbox says so in the list, and the pane stays empty", async () => {
    api.fetchInbox.mockResolvedValue({ groups: {} });
    const { split, list, pane } = renderDashboard();

    expect(await within(list()).findByRole("heading", { name: "No emails" })).toBeVisible();
    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBeEmptyDOMElement();
  });
});

describe("opening an email splits the page", () => {
  it("by clicking a row: the split is marked and the reader is in the pane", async () => {
    const user = userEvent.setup();
    const { split, list, pane } = renderDashboard();
    await loaded();

    await user.click(row(/dinner this weekend/i));

    expect(await within(pane()).findByRole("heading", { name: "Dinner this weekend?" })).toBeVisible();
    expect(split()).toHaveClass("has-selection");
    expect(await within(pane()).findByText("The body of personal-1.")).toBeVisible();
    // The list is still there beside it, with the open row marked.
    expect(within(list()).getByRole("button", { name: /dinner this weekend/i })).toHaveClass("sel");
    expect(within(list()).getByRole("button", { name: /project deadline moved to friday/i })).toBeVisible();
  });

  it("by a typed command: the same, with the action run in the pane", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "work-1", confidence: 0.9 });
    const { split, pane } = renderDashboard();
    await loaded();
    expect(split()).not.toHaveClass("has-selection");

    await runCommand(user, "summarise the email from David");

    expect(await within(pane()).findByRole("heading", { name: "Project deadline moved to Friday" })).toBeVisible();
    expect(split()).toHaveClass("has-selection");
    expect(await within(pane()).findByText("Summary of work-1.")).toBeVisible();
  });

  it("in the pane and the split that were already on the page", async () => {
    const user = userEvent.setup();
    const { split, pane } = renderDashboard();
    await loaded();
    const splitBefore = split();
    const paneBefore = pane();
    expect(paneBefore).not.toBeNull();

    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByRole("heading", { name: "Dinner this weekend?" });

    // The same two elements, with a class added and a child added. A new
    // element has no earlier width for the browser to animate from.
    expect(split()).toBe(splitBefore);
    expect(pane()).toBe(paneBefore);
  });

  it("opening another email keeps the page split", async () => {
    const user = userEvent.setup();
    const { split, pane } = renderDashboard();
    await loaded();
    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByRole("heading", { name: "Dinner this weekend?" });
    const paneBefore = pane();

    await user.click(row(/project deadline moved to friday/i));

    expect(await within(pane()).findByRole("heading", { name: "Project deadline moved to Friday" })).toBeVisible();
    expect(within(pane()).queryByRole("heading", { name: "Dinner this weekend?" })).toBeNull();
    expect(split()).toHaveClass("has-selection");
    expect(pane()).toBe(paneBefore);
  });
});

describe("when no email is open any more", () => {
  it("going back to the list unmarks the split and empties the pane, which stays", async () => {
    const user = userEvent.setup();
    const { split, pane } = renderDashboard();
    await loaded();
    const paneBefore = pane();
    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByRole("heading", { name: "Dinner this weekend?" });

    // The reader's way back. The stylesheet shows it on a narrow window only,
    // where the reader replaces the list; jsdom has it either way.
    await user.click(screen.getByRole("button", { name: "Back to inbox" }));

    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBe(paneBefore);
    expect(pane()).toBeEmptyDOMElement();
    expect(row(/dinner this weekend/i)).not.toHaveClass("sel");
  });

  it("a command naming an email that is not in the inbox does not split the page beside a blank", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "not-in-the-inbox", confidence: 0.9 });
    const { split, pane } = renderDashboard();
    await loaded();

    await runCommand(user, "summarise the email from nobody");
    // The bar has handed the id on; there is no such email to open.
    await screen.findByText("Opened the email you named.");

    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBeEmptyDOMElement();
    expect(api.summarise).not.toHaveBeenCalled();
  });
});
