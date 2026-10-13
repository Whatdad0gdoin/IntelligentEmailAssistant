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
 *  - the "Select an email to read" card is not rendered anywhere;
 *  - a row is a toggle and says so: the open email's row closes it. A command
 *    is not one, and never closes an email;
 *  - where the stylesheet slides the split, a closed reader stays in the
 *    pane, out of reach, until the split reports the end of its slide or a
 *    timer runs out, so that closing is opening backwards. Anywhere else the
 *    pane is emptied at once.
 *
 * jsdom has no matchMedia, which is how Inbox finds out whether the split
 * slides here. Without it Inbox assumes nothing moves and empties the pane at
 * once, so that is what a test gets unless it says which window it is on
 * (`onWindow`).
 *
 * Driven through Dashboard, the real shell, because that is what decides which
 * email is open: a row's click and the command bar both end in its `selected`.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "../components/Dashboard.jsx";
import Inbox from "./Inbox.jsx";
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// Inbox.jsx's CLOSE_FALLBACK_MS: how long a closed reader is kept when the
// split never reports the end of its slide.
const CLOSE_FALLBACK_MS = 600;

/** Says which window this is. Inbox asks two things before it keeps a closed
 *  reader for the slide: is the window too narrow to show both panes, and has
 *  reduced motion been asked for. With no argument it is a wide window that
 *  animates, which is the one the slide is for. */
function onWindow({ narrow = false, reducedMotion = false } = {}) {
  vi.stubGlobal("matchMedia", (query) => {
    let matches = false;
    if (/max-width/.test(query)) matches = narrow;
    else if (/prefers-reduced-motion/.test(query)) matches = reducedMotion;
    return { media: query, matches };
  });
}

/** What a browser sends when one of an element's transitions has finished.
 *  jsdom runs none, so the event is made by hand. */
function transitionEnds(element, propertyName) {
  const event = new Event("transitionend", { bubbles: true });
  Object.defineProperty(event, "propertyName", { value: propertyName });
  act(() => {
    element.dispatchEvent(event);
  });
}

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

describe("a row is a toggle", () => {
  it("each row says whether it is the open one, under the name it always had", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await loaded();
    const dinner = () => row(/dinner this weekend/i);
    const deadline = () => row(/project deadline moved to friday/i);

    expect(dinner()).toHaveAttribute("aria-pressed", "false");
    expect(deadline()).toHaveAttribute("aria-pressed", "false");

    await user.click(dinner());
    expect(dinner()).toHaveAttribute("aria-pressed", "true");
    expect(deadline()).toHaveAttribute("aria-pressed", "false");

    await user.click(deadline());
    expect(dinner()).toHaveAttribute("aria-pressed", "false");
    expect(deadline()).toHaveAttribute("aria-pressed", "true");
  });

  it("clicking the open email's row closes it, and the list has the page again", async () => {
    const user = userEvent.setup();
    const { split, list, pane } = renderDashboard();
    await loaded();
    const paneBefore = pane();
    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByRole("heading", { name: "Dinner this weekend?" });

    await user.click(row(/dinner this weekend/i));

    // As it was before anything was opened. No window was named, so nothing
    // slides and the pane is empty at once.
    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBe(paneBefore);
    expect(pane()).toBeEmptyDOMElement();
    expect(row(/dinner this weekend/i)).not.toHaveClass("sel");
    expect(row(/dinner this weekend/i)).toHaveAttribute("aria-pressed", "false");
    expect(within(list()).getByRole("button", { name: /project deadline moved to friday/i })).toBeVisible();

    // And a third click opens it again.
    await user.click(row(/dinner this weekend/i));
    expect(await within(pane()).findByRole("heading", { name: "Dinner this weekend?" })).toBeVisible();
    expect(split()).toHaveClass("has-selection");
  });
});

describe("a command does not close an email", () => {
  // On a window that slides, where a close would leave the pane marked.
  beforeEach(() => onWindow());

  it("naming the email that is already open keeps it open, and runs the action there", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: "work-1", confidence: 0.9 });
    const { split, pane } = renderDashboard();
    await loaded();
    await user.click(row(/project deadline moved to friday/i));
    await within(pane()).findByText("The body of work-1.");

    await runCommand(user, "summarise the email from David");

    expect(await within(pane()).findByText("Summary of work-1.")).toBeVisible();
    expect(split()).toHaveClass("has-selection");
    expect(pane()).not.toHaveAttribute("inert");
    expect(row(/project deadline moved to friday/i)).toHaveAttribute("aria-pressed", "true");
  });

  it("naming no email works on the open one, and keeps it open", async () => {
    const user = userEvent.setup();
    api.voiceIntent.mockResolvedValue({ intent: "summarise", target_email_id: null, confidence: 0.9 });
    const { split, pane } = renderDashboard();
    await loaded();
    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByText("The body of personal-1.");

    await runCommand(user, "summarise this");

    expect(await within(pane()).findByText("Summary of personal-1.")).toBeVisible();
    expect(split()).toHaveClass("has-selection");
    expect(pane()).not.toHaveAttribute("inert");
    expect(row(/dinner this weekend/i)).toHaveAttribute("aria-pressed", "true");
  });
});

describe("closing an email on a window that slides", () => {
  beforeEach(() => onWindow());

  /** Renders, and opens the dinner email with its body loaded. */
  async function withDinnerOpen() {
    const user = userEvent.setup();
    const found = renderDashboard();
    await loaded();
    await user.click(row(/dinner this weekend/i));
    await within(found.pane()).findByText("The body of personal-1.");
    return { user, ...found };
  }

  it("the mark goes at once, and the reader stays, out of reach, until the list's column has finished widening", async () => {
    const { user, split, pane } = await withDinnerOpen();
    const paneBefore = pane();
    expect(pane()).not.toHaveAttribute("inert");
    expect(pane()).not.toHaveAttribute("aria-hidden");

    await user.click(row(/dinner this weekend/i));

    // Closed, as far as the layout and the list go: this is what starts the
    // list widening.
    expect(split()).not.toHaveClass("has-selection");
    expect(row(/dinner this weekend/i)).not.toHaveClass("sel");
    expect(row(/dinner this weekend/i)).toHaveAttribute("aria-pressed", "false");
    // The reader is still drawn, as it was, for the slide to take away...
    expect(pane()).toBe(paneBefore);
    expect(within(pane()).getByText("The body of personal-1.")).toBeInTheDocument();
    // ...and is not there to be used.
    expect(pane()).toHaveAttribute("inert");
    expect(pane()).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("heading", { name: "Dinner this weekend?" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^summarise$/i })).toBeNull();

    transitionEnds(split(), "grid-template-columns");

    expect(pane()).toBe(paneBefore);
    expect(pane()).toBeEmptyDOMElement();
    expect(pane()).not.toHaveAttribute("inert");
    expect(pane()).not.toHaveAttribute("aria-hidden");
  });

  it("no other transition ending takes the reader away", async () => {
    const { user, split, pane } = await withDinnerOpen();
    await user.click(row(/dinner this weekend/i));

    // The gap ends with the column, and the rest bubble up from inside: a
    // row's hover, the pane's own fade.
    transitionEnds(split(), "column-gap");
    transitionEnds(row(/dinner this weekend/i), "background-color");
    transitionEnds(row(/dinner this weekend/i), "grid-template-columns");
    transitionEnds(pane(), "opacity");

    expect(within(pane()).getByText("The body of personal-1.")).toBeInTheDocument();
    expect(pane()).toHaveAttribute("inert");
  });

  it("if the end of the slide is never reported, a timer takes the reader away", async () => {
    const { pane } = await withDinnerOpen();
    // The clock is stopped from here, and user-event waits on it, so the
    // click is sent directly.
    vi.useFakeTimers();

    fireEvent.click(row(/dinner this weekend/i));
    expect(pane()).toHaveAttribute("inert");

    act(() => {
      vi.advanceTimersByTime(CLOSE_FALLBACK_MS - 1);
    });
    expect(within(pane()).getByText("The body of personal-1.")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(pane()).toBeEmptyDOMElement();
    expect(pane()).not.toHaveAttribute("inert");
  });

  it("opening another email while one is closing drops the removal and shows the new one", async () => {
    const { split, pane } = await withDinnerOpen();
    vi.useFakeTimers();
    fireEvent.click(row(/dinner this weekend/i));
    expect(pane()).toHaveAttribute("inert");

    fireEvent.click(row(/project deadline moved to friday/i));
    await act(async () => {});   // the new email's body

    expect(split()).toHaveClass("has-selection");
    expect(pane()).not.toHaveAttribute("inert");
    expect(pane()).not.toHaveAttribute("aria-hidden");
    expect(within(pane()).getByRole("heading", { name: "Project deadline moved to Friday" })).toBeInTheDocument();
    expect(within(pane()).queryByRole("heading", { name: "Dinner this weekend?" })).toBeNull();

    // Nothing is left waiting to empty the pane: not the timer, and not the
    // end of the slide that the opening itself runs.
    act(() => {
      vi.advanceTimersByTime(CLOSE_FALLBACK_MS * 5);
    });
    transitionEnds(split(), "grid-template-columns");

    expect(within(pane()).getByRole("heading", { name: "Project deadline moved to Friday" })).toBeInTheDocument();
    expect(within(pane()).getByText("The body of work-1.")).toBeInTheDocument();
    expect(split()).toHaveClass("has-selection");
  });

  it("the same email opened again while it is closing is the reader that was there, with what it held", async () => {
    const { user, split, pane } = await withDinnerOpen();
    await user.click(within(pane()).getByRole("button", { name: /^summarise$/i }));
    await within(pane()).findByText("Summary of personal-1.");
    vi.useFakeTimers();

    fireEvent.click(row(/dinner this weekend/i));
    expect(pane()).toHaveAttribute("inert");
    fireEvent.click(row(/dinner this weekend/i));

    expect(split()).toHaveClass("has-selection");
    expect(pane()).not.toHaveAttribute("inert");
    // The removal was dropped, so nothing was unmounted and the summary is
    // still open. Once the reader has gone, opening the email starts clean.
    expect(within(pane()).getByText("Summary of personal-1.")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(CLOSE_FALLBACK_MS * 5);
    });
    transitionEnds(split(), "grid-template-columns");
    expect(within(pane()).getByText("Summary of personal-1.")).toBeInTheDocument();
    expect(api.summarise).toHaveBeenCalledTimes(1);
  });

  it("another row switches email without closing anything", async () => {
    const { user, split, pane } = await withDinnerOpen();
    const paneBefore = pane();

    await user.click(row(/project deadline moved to friday/i));

    expect(split()).toHaveClass("has-selection");
    expect(pane()).toBe(paneBefore);
    expect(pane()).not.toHaveAttribute("inert");
    expect(await within(pane()).findByRole("heading", { name: "Project deadline moved to Friday" })).toBeVisible();
    expect(within(pane()).queryByRole("heading", { name: "Dinner this weekend?" })).toBeNull();
  });

  it("a reader that is leaving is not handed a command", () => {
    // Inbox on its own: Dashboard never has a command for an email it has
    // closed, short of the mailbox changing under an open one.
    const props = {
      groups: GROUPS,
      loading: false,
      error: null,
      filter: "all",
      setFilter: vi.fn(),
      setSelected: vi.fn(),
      bodyLoading: false,
      onRetry: vi.fn(),
      onActionConsumed: vi.fn(),
      voiceEnabled: true,
    };
    const { container, rerender } = render(
      <Inbox {...props} selected="work-1" openEmail={BY_ID["work-1"]} openBody="The body of work-1." pendingAction={null} />
    );

    rerender(
      <Inbox
        {...props}
        selected={null}
        openEmail={null}
        openBody={undefined}
        pendingAction={{ intent: "summarise", emailId: "work-1" }}
      />
    );

    const pane = container.querySelector(".inbox-right");
    expect(pane).toHaveAttribute("inert");
    expect(within(pane).getByText("The body of work-1.")).toBeInTheDocument();
    expect(api.summarise).not.toHaveBeenCalled();
  });
});

describe("closing an email where nothing slides", () => {
  it("with reduced motion asked for, the pane is emptied at once", async () => {
    onWindow({ reducedMotion: true });
    const user = userEvent.setup();
    const { split, pane } = renderDashboard();
    await loaded();
    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByRole("heading", { name: "Dinner this weekend?" });

    await user.click(row(/dinner this weekend/i));

    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBeEmptyDOMElement();
    expect(pane()).not.toHaveAttribute("inert");
  });

  it("on a narrow window, going back to the list unmarks the split and empties the pane, which stays", async () => {
    onWindow({ narrow: true });
    const user = userEvent.setup();
    const { split, pane } = renderDashboard();
    await loaded();
    const paneBefore = pane();
    await user.click(row(/dinner this weekend/i));
    await within(pane()).findByRole("heading", { name: "Dinner this weekend?" });

    // The reader's way back. The stylesheet shows it on a narrow window only,
    // where the reader replaces the list and there is no row to press; jsdom
    // has it either way. One pane is swapped for the other with no slide, so
    // there is nothing to keep the reader for.
    await user.click(screen.getByRole("button", { name: "Back to inbox" }));

    expect(split()).not.toHaveClass("has-selection");
    expect(pane()).toBe(paneBefore);
    expect(pane()).toBeEmptyDOMElement();
    expect(pane()).not.toHaveAttribute("inert");
    expect(row(/dinner this weekend/i)).not.toHaveClass("sel");
  });
});

describe("when the email chosen is not in the inbox", () => {
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
