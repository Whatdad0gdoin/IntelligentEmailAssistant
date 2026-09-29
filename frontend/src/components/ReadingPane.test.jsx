/**
 * Reading pane behaviour that requirements depend on.
 *
 * Three things are checked here, and nothing about how any of it looks:
 *
 *  - FR-03. The draft is editable and approval is an explicit, separate act.
 *    The backend suite asserts there is no send route; this asserts the same
 *    guarantee from the other end, because a send button wired to anything at
 *    all would break the requirement no matter what the server exposes.
 *  - FR-01. An unverified summary is shown AND shown as unverified. Withholding
 *    it and quietly shipping it are both wrong; the grounding layer exists so
 *    the reader can see which claims failed.
 *  - SR-01. jsdom has no speechSynthesis, so this file renders the pane exactly
 *    as Firefox or Safari would. Read Aloud must be absent rather than present
 *    and dead. The supported browser is covered in ReadingPane.voice.test.jsx.
 *
 * The api client is mocked to the two calls this pane can make. That keeps the
 * tests offline, and it means a third call added later fails loudly here
 * instead of quietly reaching the network.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReadingPane from "./ReadingPane.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  summarise: vi.fn(),
  draft: vi.fn(),
}));

const EMAIL = {
  id: "email-1",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
};

const BODY =
  "The deadline has moved to Friday. Can we reschedule Thursday's meeting to Wednesday afternoon?";

const DRAFT = {
  draft: "Hi David,\n\nWednesday afternoon works for me.\n\nThanks,\nJames",
  grounded: true,
  ungrounded_flags: [],
};

function renderPane(props = {}) {
  return render(<ReadingPane email={EMAIL} body={BODY} {...props} />);
}

/** Renders the pane, generates a draft, and hands back the draft textarea. */
async function generateDraft(user, payload = DRAFT) {
  api.draft.mockResolvedValue(payload);
  renderPane();
  await user.click(screen.getByRole("button", { name: /draft reply/i }));
  return await screen.findByRole("textbox", { name: /draft reply, editable/i });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("FR-03: the draft is the user's to edit", () => {
  it("renders the generated draft in a textarea", async () => {
    const user = userEvent.setup();
    const textarea = await generateDraft(user);

    expect(textarea.tagName).toBe("TEXTAREA");
    expect(textarea).toHaveValue(DRAFT.draft);
  });

  it("lets the user change the text, rather than showing it read-only", async () => {
    const user = userEvent.setup();
    const textarea = await generateDraft(user);

    expect(textarea).toBeEnabled();
    await user.clear(textarea);
    await user.type(textarea, "Wednesday suits me.");

    // The typed value is what matters: a readOnly or disabled textarea would
    // still render the draft and still look right on screen.
    expect(textarea).toHaveValue("Wednesday suits me.");
  });

  it("does not render a draft panel until one is asked for", () => {
    renderPane();
    expect(screen.queryByRole("textbox", { name: /draft reply, editable/i })).toBeNull();
  });
});

describe("FR-03: approval is explicit, and nothing sends", () => {
  it("offers an Approve control with the draft", async () => {
    const user = userEvent.setup();
    await generateDraft(user);

    expect(screen.getByRole("button", { name: /approve/i })).toBeEnabled();
  });

  it("offers no send control before Approve is clicked", async () => {
    const user = userEvent.setup();
    await generateDraft(user);

    // Any control at all: the requirement is that the path does not exist,
    // not that a particular button is hidden.
    expect(screen.queryByRole("button", { name: /send|deliver|reply now/i })).toBeNull();
  });

  it("offers no send control after Approve is clicked either", async () => {
    const user = userEvent.setup();
    await generateDraft(user);
    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(screen.queryByRole("button", { name: /send|deliver|reply now/i })).toBeNull();
  });

  it("approving fires no request - it marks the text reviewed and stops", async () => {
    const user = userEvent.setup();
    await generateDraft(user);
    expect(api.draft).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(api.draft).toHaveBeenCalledTimes(1);
    expect(api.summarise).not.toHaveBeenCalled();
  });

  it("the api client has no send endpoint for a button to be wired to", async () => {
    // The real module, not the mock: this is the client the app ships with.
    const actual = await vi.importActual("../api/client.js");
    expect(Object.keys(actual).filter((name) => /send|deliver/i.test(name))).toEqual([]);
  });

  it("editing an approved draft withdraws the approval", async () => {
    const user = userEvent.setup();
    const textarea = await generateDraft(user);
    const approve = screen.getByRole("button", { name: /approve/i });

    await user.click(approve);
    expect(approve).toBeDisabled();          // already approved, nothing to do

    await user.type(textarea, " Actually, Thursday is better.");

    // Text that changed after approval has not been approved. Leaving the
    // button in its done state would claim review of words nobody read.
    expect(approve).toBeEnabled();
  });

  it("an empty draft cannot be approved", async () => {
    const user = userEvent.setup();
    const textarea = await generateDraft(user);

    await user.clear(textarea);

    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
  });
});

describe("FR-01: an unverified summary is shown, and shown as unverified", () => {
  const UNGROUNDED = {
    email_id: EMAIL.id,
    summary: ["David moved the deadline to Friday.", "He suggests meeting on Monday."],
    action_items: [],
    grounded: false,
    ungrounded_flags: [{ claim: "Monday", reason: "not found in the source email" }],
  };

  async function summarise(user, payload) {
    api.summarise.mockResolvedValue(payload);
    await user.click(screen.getByRole("button", { name: /^summarise$/i }));
    return await screen.findByText(/could not be verified|every checkable claim/i);
  }

  it("shows the warning rather than hiding the failure", async () => {
    const user = userEvent.setup();
    renderPane();
    const notice = await summarise(user, UNGROUNDED);

    expect(notice).toBeVisible();
    expect(notice.textContent).toMatch(/could not be verified/i);
  });

  it("names the claim that failed, so the reader knows what to check", async () => {
    const user = userEvent.setup();
    renderPane();
    await summarise(user, UNGROUNDED);

    expect(screen.getByText("Monday")).toBeVisible();
    expect(screen.getByText(/not found in the source email/i)).toBeVisible();
  });

  it("still renders the summary itself - the text is flagged, not withheld", async () => {
    const user = userEvent.setup();
    renderPane();
    await summarise(user, UNGROUNDED);

    expect(screen.getByText(/He suggests meeting on Monday\./)).toBeVisible();
    expect(screen.getByText(/David moved the deadline to Friday\./)).toBeVisible();
  });

  it("a grounded summary carries the verified notice and no warning", async () => {
    const user = userEvent.setup();
    renderPane();
    await summarise(user, {
      ...UNGROUNDED,
      summary: ["David moved the deadline to Friday."],
      grounded: true,
      ungrounded_flags: [],
    });

    expect(screen.getByText(/every checkable claim was found/i)).toBeVisible();
    expect(screen.queryByText(/could not be verified/i)).toBeNull();
  });
});

describe("SR-01: a browser without speech synthesis", () => {
  it("omits Read Aloud instead of rendering a button that cannot work", () => {
    renderPane();
    expect(screen.queryByRole("button", { name: /read aloud/i })).toBeNull();
  });

  it("keeps every AI action reachable by clicking", () => {
    renderPane();
    expect(screen.getByRole("button", { name: /^summarise$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /draft reply/i })).toBeEnabled();
  });

  it("a spoken 'read it' request falls back to summarising rather than failing", async () => {
    // FR-05 dispatches into this pane. With no speech synthesis the read
    // branch has nothing to speak, so it must still produce the summary.
    api.summarise.mockResolvedValue({
      email_id: EMAIL.id, summary: ["Deadline moved to Friday."],
      action_items: [], grounded: true, ungrounded_flags: [],
    });
    renderPane({ pendingAction: { intent: "read", emailId: EMAIL.id }, onActionConsumed: vi.fn() });

    expect(await screen.findByText("Deadline moved to Friday.")).toBeVisible();
    expect(api.summarise).toHaveBeenCalledWith(EMAIL.id);
  });
});
