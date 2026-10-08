/**
 * The translation language chosen in Settings (FR-07; the Week 11 Settings
 * wireframe lists it, defaulting to English).
 *
 * The preference only matters if it reaches the request, so these tests drive
 * the real shell: choose in Settings, open an email, press Translate, and look
 * at what was asked for. Stored under mailkit:translationLang by usePreference,
 * like the other two preferences, and read through the same guard as the
 * recognition language so a stale value cannot become a refused request.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "./Dashboard.jsx";
import * as api from "../api/client.js";

vi.mock("../api/client.js", () => ({
  fetchInbox: vi.fn(),
  getEmail: vi.fn(),
  summarise: vi.fn(),
  draft: vi.fn(),
  translate: vi.fn(),
}));

const EMAIL = {
  id: "email-1",
  sender_name: "David Robinson",
  sender: "d.robinson@northgate.com.au",
  subject: "Project deadline moved to Friday",
  snippet: "Can we reschedule our Thursday meeting",
  category: "Work",
  received_at: "2026-08-25T09:24:00+10:00",
  unread: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  api.fetchInbox.mockResolvedValue({ groups: { Work: [EMAIL] } });
  api.getEmail.mockResolvedValue({ ...EMAIL, body: "The deadline has moved to Friday." });
  api.translate.mockImplementation(async ({ language }) => ({
    email_id: EMAIL.id,
    language,
    subject: `[${language}] subject`,
    translation: `[${language}] body`,
    grounded: true,
    ungrounded_flags: [],
  }));
});

function renderDashboard() {
  return render(<Dashboard user={{ email: "student@monash.edu" }} onLogout={vi.fn()} />);
}

const emailRow = () => screen.findByRole("button", { name: /project deadline moved to friday/i });

async function translateOpenEmail(user) {
  await user.click(await emailRow());
  await user.click(await screen.findByRole("button", { name: /^translate$/i }));
}

describe("the translation language in Settings", () => {
  it("defaults to English, is remembered, and is what Translate asks for", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await emailRow();

    await user.click(screen.getByRole("button", { name: /settings/i }));
    const select = screen.getByRole("combobox", { name: /translation language/i });
    expect(select).toHaveValue("English");

    await user.selectOptions(select, "Japanese");
    expect(JSON.parse(window.localStorage.getItem("mailkit:translationLang"))).toBe("Japanese");

    await user.click(screen.getByRole("button", { name: /^inbox$/i }));
    await translateOpenEmail(user);

    expect(api.translate.mock.calls[0][0]).toEqual({ emailId: EMAIL.id, language: "Japanese" });
    expect(await screen.findByRole("heading", { name: "[Japanese] subject" })).toBeVisible();
  });

  it("survives a reload: a stored choice is used from the first translation", async () => {
    window.localStorage.setItem("mailkit:translationLang", JSON.stringify("Korean"));
    const user = userEvent.setup();
    renderDashboard();

    await translateOpenEmail(user);

    expect(api.translate.mock.calls[0][0]).toEqual({ emailId: EMAIL.id, language: "Korean" });
  });

  it("falls back to English when the stored choice is not one on offer", async () => {
    window.localStorage.setItem("mailkit:translationLang", JSON.stringify("Klingon"));
    const user = userEvent.setup();
    renderDashboard();

    await translateOpenEmail(user);
    expect(api.translate.mock.calls[0][0]).toEqual({ emailId: EMAIL.id, language: "English" });

    await user.click(screen.getByRole("button", { name: /settings/i }));
    expect(screen.getByRole("combobox", { name: /translation language/i })).toHaveValue("English");
  });

  it("is offered whatever the voice setting, because translation needs no speech", async () => {
    window.localStorage.setItem("mailkit:voiceEnabled", JSON.stringify(false));
    const user = userEvent.setup();
    renderDashboard();
    await emailRow();

    await user.click(screen.getByRole("button", { name: /settings/i }));

    expect(screen.getByRole("combobox", { name: /translation language/i })).toBeEnabled();
  });
});
