/**
 * Translation in the reading pane (FR-07).
 *
 * Two things can be translated -- the open email, and a drafted reply -- and
 * they fail in different ways, so they are tested apart:
 *
 *  - The email. What is asked for (this email, in the language chosen in
 *    Settings), what is shown (subject and body with their line breaks, and
 *    the backend's check on the figures), and the states around it: loading,
 *    error, a language switch, an answer that arrives after a newer request.
 *  - The draft. Its translation goes back into the editable textarea, so the
 *    FR-03 guarantees have to survive it: the new words are not approved
 *    words, Undo puts the old ones back, and there is still no send control.
 *
 * The api client is mocked to the three calls this pane can make.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReadingPane from "./ReadingPane.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  summarise: vi.fn(),
  draft: vi.fn(),
  translate: vi.fn(),
}));

const EMAIL = {
  id: "email-1",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
};

const BODY = "Hi,\n\nCan we move Thursday's meeting to Friday at 2pm?";

const SPANISH = {
  email_id: EMAIL.id,
  language: "Spanish",
  subject: "Plazo del proyecto trasladado al viernes",
  translation: "Hola:\n\n¿Podemos pasar la reunión del jueves al viernes a las 2pm?",
  grounded: true,
  ungrounded_flags: [],
};

const FRENCH = {
  ...SPANISH,
  language: "French",
  subject: "Échéance du projet déplacée à vendredi",
  translation: "Bonjour,\n\nPouvons-nous déplacer la réunion de jeudi à vendredi à 2pm ?",
};

const DRAFT = {
  draft: "Hi David,\n\nFriday at 2pm works for me.\n\nThanks,\nJames",
  grounded: true,
  ungrounded_flags: [],
  tone: "neutral",
};

const DRAFT_FRENCH = {
  language: "French",
  translation: "Bonjour David,\n\nVendredi à 2pm me convient.\n\nMerci,\nJames",
  grounded: true,
  ungrounded_flags: [],
};

function renderPane(props = {}) {
  return render(<ReadingPane email={EMAIL} body={BODY} {...props} />);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Presses Tab until `target` has focus, as a keyboard user would. */
async function tabTo(user, target, limit = 30) {
  for (let i = 0; i < limit && document.activeElement !== target; i += 1) {
    await user.tab();
  }
  expect(target).toHaveFocus();
}

const translateButton = () => screen.getByRole("button", { name: /^translate$/i });
const panel = () => screen.getByRole("region", { name: "Translation" });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("FR-07: translating the open email", () => {
  it("asks for this email in the language chosen in Settings, and shows the translation", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(SPANISH);
    renderPane({ translationLang: "Spanish" });

    await user.click(translateButton());

    expect(api.translate).toHaveBeenCalledTimes(1);
    expect(api.translate.mock.calls[0][0]).toEqual({ emailId: EMAIL.id, language: "Spanish" });
    expect(await screen.findByRole("heading", { name: SPANISH.subject })).toBeVisible();
    // The body keeps its line breaks: the text node is the translation as sent.
    const body = within(panel()).getByText(/Podemos pasar la reunión/);
    expect(body.textContent).toBe(SPANISH.translation);
    // Marked as the language it is written in, for screen readers and fonts.
    expect(body.closest("[lang]")).toHaveAttribute("lang", "es");
  });

  it("starts in English when nothing was chosen", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue({ ...SPANISH, language: "English" });
    renderPane();

    await user.click(translateButton());

    expect(api.translate.mock.calls[0][0]).toEqual({ emailId: EMAIL.id, language: "English" });
    expect(within(panel()).getByRole("combobox", { name: /translate into/i })).toHaveValue("English");
  });

  it("switching the language on the panel translates again, in that language", async () => {
    const user = userEvent.setup();
    api.translate.mockImplementation(async ({ language }) => (language === "French" ? FRENCH : SPANISH));
    renderPane({ translationLang: "Spanish" });
    await user.click(translateButton());
    await screen.findByRole("heading", { name: SPANISH.subject });

    await user.selectOptions(within(panel()).getByRole("combobox", { name: /translate into/i }), "French");

    expect(api.translate).toHaveBeenCalledTimes(2);
    expect(api.translate.mock.calls[1][0]).toEqual({ emailId: EMAIL.id, language: "French" });
    expect(await screen.findByRole("heading", { name: FRENCH.subject })).toBeVisible();
    expect(screen.queryByRole("heading", { name: SPANISH.subject })).toBeNull();
  });

  it("shows that it is working while the request is in flight", async () => {
    const user = userEvent.setup();
    const pending = deferred();
    api.translate.mockReturnValue(pending.promise);
    renderPane({ translationLang: "Spanish" });

    await user.click(translateButton());

    expect(screen.getByLabelText("Translating")).toBeInTheDocument();
    expect(translateButton()).toBeDisabled();

    pending.resolve(SPANISH);
    expect(await screen.findByRole("heading", { name: SPANISH.subject })).toBeVisible();
    expect(screen.queryByLabelText("Translating")).toBeNull();
    expect(translateButton()).toBeEnabled();
  });

  it("shows the error rather than an empty translation", async () => {
    const user = userEvent.setup();
    api.translate.mockRejectedValue(new Error("The AI service is unavailable. Please try again in a moment."));
    renderPane({ translationLang: "Spanish" });

    await user.click(translateButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(/AI service is unavailable/i);
    expect(screen.queryByRole("heading", { name: SPANISH.subject })).toBeNull();
    expect(translateButton()).toBeEnabled();   // free to try again
  });

  it("drops an answer that arrives after a newer request", async () => {
    const user = userEvent.setup();
    const slowSpanish = deferred();
    api.translate
      .mockReturnValueOnce(slowSpanish.promise)
      .mockResolvedValueOnce(FRENCH);
    renderPane({ translationLang: "Spanish" });

    await user.click(translateButton());
    await user.selectOptions(within(panel()).getByRole("combobox", { name: /translate into/i }), "French");
    expect(await screen.findByRole("heading", { name: FRENCH.subject })).toBeVisible();

    slowSpanish.resolve(SPANISH);
    await waitFor(() => expect(api.translate.mock.calls[0][1].signal.aborted).toBe(true));
    expect(screen.queryByRole("heading", { name: SPANISH.subject })).toBeNull();
    expect(screen.getByRole("heading", { name: FRENCH.subject })).toBeVisible();
  });

  it("flags figures that did not survive, naming them, without withholding the text", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue({
      ...SPANISH,
      translation: "Hola:\n\n¿Podemos pasar la reunión del jueves al viernes a las 14:00?",
      grounded: false,
      ungrounded_flags: [
        { claim: "14", reason: "number not in the original" },
        { claim: "2", reason: "number missing from the translation" },
      ],
    });
    renderPane({ translationLang: "Spanish" });

    await user.click(translateButton());

    expect(await screen.findByText(/could not be verified against the original/i)).toBeVisible();
    expect(screen.getByText("number not in the original")).toBeVisible();
    expect(screen.getByText("number missing from the translation")).toBeVisible();
    expect(within(panel()).getByText(/a las 14:00/)).toBeVisible();
    expect(within(panel()).getByText("Unverified")).toBeVisible();
  });

  it("a clean result says what was checked", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(SPANISH);
    renderPane({ translationLang: "Spanish" });

    await user.click(translateButton());

    expect(await screen.findByText(/every number, link and email address in the original/i)).toBeVisible();
  });

  it("can be dismissed", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(SPANISH);
    renderPane({ translationLang: "Spanish" });
    await user.click(translateButton());
    await screen.findByRole("heading", { name: SPANISH.subject });

    await user.click(screen.getByRole("button", { name: /dismiss translation/i }));

    expect(screen.queryByRole("region", { name: "Translation" })).toBeNull();
  });

  it("is reachable and usable from the keyboard", async () => {
    const user = userEvent.setup();
    api.translate.mockImplementation(async ({ language }) => (language === "French" ? FRENCH : SPANISH));
    renderPane({ translationLang: "Spanish" });

    await tabTo(user, translateButton());
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: SPANISH.subject })).toBeVisible();

    const picker = within(panel()).getByRole("combobox", { name: /translate into/i });
    await tabTo(user, picker);
    await user.selectOptions(picker, "French");
    expect(await screen.findByRole("heading", { name: FRENCH.subject })).toBeVisible();

    await tabTo(user, screen.getByRole("button", { name: /dismiss translation/i }));
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("region", { name: "Translation" })).toBeNull();
  });
});

describe("FR-07 with FR-03: translating the draft", () => {
  async function draftOnScreen(user, props = {}) {
    api.draft.mockResolvedValue(DRAFT);
    renderPane(props);
    await user.click(screen.getByRole("button", { name: /draft reply/i }));
    return screen.findByRole("textbox", { name: /draft reply, editable/i });
  }

  it("translates the text in the textarea and puts the translation back there, still editable", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(DRAFT_FRENCH);
    const textarea = await draftOnScreen(user, { translationLang: "French" });

    await user.click(screen.getByRole("button", { name: /translate draft/i }));

    expect(api.translate).toHaveBeenCalledWith({ text: DRAFT.draft, language: "French" });
    await waitFor(() => expect(textarea).toHaveValue(DRAFT_FRENCH.translation));
    await user.type(textarea, " Merci encore.");
    expect(textarea).toHaveValue(`${DRAFT_FRENCH.translation} Merci encore.`);
  });

  it("translates the draft as edited, into the language picked beside it", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue({ ...DRAFT_FRENCH, language: "German", translation: "Hallo David" });
    const textarea = await draftOnScreen(user, { translationLang: "French" });

    await user.clear(textarea);
    await user.type(textarea, "Hi David");
    await user.selectOptions(screen.getByRole("combobox", { name: /translate draft into/i }), "German");
    await user.click(screen.getByRole("button", { name: /translate draft/i }));

    expect(api.translate).toHaveBeenCalledWith({ text: "Hi David", language: "German" });
    await waitFor(() => expect(textarea).toHaveValue("Hallo David"));
  });

  it("Undo translation puts back the text from before, and then goes away", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(DRAFT_FRENCH);
    const textarea = await draftOnScreen(user, { translationLang: "French" });
    expect(screen.queryByRole("button", { name: /undo translation/i })).toBeNull();

    await user.click(screen.getByRole("button", { name: /translate draft/i }));
    await waitFor(() => expect(textarea).toHaveValue(DRAFT_FRENCH.translation));
    await user.click(screen.getByRole("button", { name: /undo translation/i }));

    expect(textarea).toHaveValue(DRAFT.draft);
    expect(screen.queryByRole("button", { name: /undo translation/i })).toBeNull();
  });

  it("withdraws an approval: the translated words have not been reviewed", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(DRAFT_FRENCH);
    const textarea = await draftOnScreen(user, { translationLang: "French" });
    const approve = screen.getByRole("button", { name: /approve/i });

    await user.click(approve);
    expect(approve).toBeDisabled();
    expect(approve).toHaveTextContent("Approved");

    await user.click(screen.getByRole("button", { name: /translate draft/i }));
    await waitFor(() => expect(textarea).toHaveValue(DRAFT_FRENCH.translation));

    expect(approve).toBeEnabled();
    expect(approve).toHaveTextContent(/^Approve$/);
  });

  it("undoing withdraws an approval too", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(DRAFT_FRENCH);
    const textarea = await draftOnScreen(user, { translationLang: "French" });
    await user.click(screen.getByRole("button", { name: /translate draft/i }));
    await waitFor(() => expect(textarea).toHaveValue(DRAFT_FRENCH.translation));
    const approve = screen.getByRole("button", { name: /approve/i });
    await user.click(approve);

    await user.click(screen.getByRole("button", { name: /undo translation/i }));

    expect(approve).toBeEnabled();
  });

  it("offers no send control, before or after translating and approving", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(DRAFT_FRENCH);
    const textarea = await draftOnScreen(user, { translationLang: "French" });

    await user.click(screen.getByRole("button", { name: /translate draft/i }));
    await waitFor(() => expect(textarea).toHaveValue(DRAFT_FRENCH.translation));
    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(screen.queryByRole("button", { name: /send|deliver|reply now/i })).toBeNull();
    // Translate is the only extra call, and it was asked for text, not delivery.
    expect(Object.keys(api.translate.mock.calls[0][0]).sort()).toEqual(["language", "text"]);
  });

  it("shows the check on the translated draft", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue({
      ...DRAFT_FRENCH,
      grounded: false,
      ungrounded_flags: [{ claim: "2", reason: "number missing from the translation" }],
    });
    await draftOnScreen(user, { translationLang: "French" });

    await user.click(screen.getByRole("button", { name: /translate draft/i }));

    expect(await screen.findByText(/could not be verified against the draft before it was translated/i))
      .toBeVisible();
    expect(screen.getByText("number missing from the translation")).toBeVisible();
  });

  it("a failed translation leaves the draft as it was and says why", async () => {
    const user = userEvent.setup();
    api.translate.mockRejectedValue(new Error("This session has used its allowance of 100 AI requests."));
    const textarea = await draftOnScreen(user, { translationLang: "French" });

    await user.click(screen.getByRole("button", { name: /translate draft/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/allowance/i);
    expect(textarea).toHaveValue(DRAFT.draft);
    expect(screen.queryByRole("button", { name: /undo translation/i })).toBeNull();
  });

  it("a regenerated draft starts untranslated, with nothing to undo", async () => {
    const user = userEvent.setup();
    api.translate.mockResolvedValue(DRAFT_FRENCH);
    const textarea = await draftOnScreen(user, { translationLang: "French" });
    await user.click(screen.getByRole("button", { name: /translate draft/i }));
    await waitFor(() => expect(textarea).toHaveValue(DRAFT_FRENCH.translation));

    api.draft.mockResolvedValue({ ...DRAFT, draft: "Hi David,\n\nNoted.\n\nJames" });
    // The toolbar's and the panel's: both regenerate.
    await user.click(screen.getAllByRole("button", { name: /regenerate/i })[0]);

    await waitFor(() => expect(textarea).toHaveValue("Hi David,\n\nNoted.\n\nJames"));
    expect(screen.queryByRole("button", { name: /undo translation/i })).toBeNull();
  });

  it("cannot translate an empty draft", async () => {
    const user = userEvent.setup();
    const textarea = await draftOnScreen(user, { translationLang: "French" });

    await user.clear(textarea);

    expect(screen.getByRole("button", { name: /translate draft/i })).toBeDisabled();
    expect(api.translate).not.toHaveBeenCalled();
  });
});
