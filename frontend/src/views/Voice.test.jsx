/**
 * Voice Commands view (FR-05): which language the recogniser is given, and
 * what the page tells the user about where their audio goes.
 *
 * jsdom has no SpeechRecognition, and Voice.jsx looks the constructor up once
 * at module load, so a stand-in is installed with vi.hoisted -- before the
 * import below runs -- and every instance the view creates is recorded.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Voice from "./Voice.jsx";

vi.mock("../api/client.js", () => ({ voiceIntent: vi.fn() }));

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

afterEach(() => {
  recognisers.length = 0;
  vi.restoreAllMocks();
});

function renderVoice(props = {}) {
  return render(<Voice emails={[]} onRun={vi.fn()} onBack={vi.fn()} {...props} />);
}

async function startListening() {
  await userEvent.setup().click(screen.getByRole("button", { name: /start listening/i }));
  expect(recognisers).toHaveLength(1);
  return recognisers[0];
}

describe("the recogniser's language", () => {
  it("is en-AU by default, not the browser's own language", async () => {
    // The original bug: navigator.language is the browser's menu language, so
    // an Indonesian Chrome handed the recogniser id-ID for English commands.
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("id-ID");
    expect(navigator.language).toBe("id-ID");
    renderVoice();

    expect((await startListening()).lang).toBe("en-AU");
  });

  it("is the one chosen in Settings", async () => {
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("en-US");
    renderVoice({ speechLang: "en-IN" });

    expect((await startListening()).lang).toBe("en-IN");
  });
});

describe("what the page says about the audio", () => {
  it("says our server never receives it", () => {
    renderVoice();
    expect(screen.getByText(/our server never receives your audio/i)).toBeInTheDocument();
  });

  it("says the browser's speech service may, and names who runs it", () => {
    renderVoice();
    expect(screen.getByText(/chrome sends it to google unless on-device recognition is used/i))
      .toBeInTheDocument();
    expect(screen.getByText(/edge sends it to microsoft/i)).toBeInTheDocument();
  });

  it("no longer claims the voice is processed in the browser", () => {
    renderVoice();
    expect(screen.queryByText(/processed\s+in the browser/i)).toBeNull();
  });
});
