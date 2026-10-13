import { describe, expect, it } from "vitest";

import { voiceStatus } from "./voiceStatus.js";

const CHROME = { tts: true, stt: true };
const FIREFOX = { tts: true, stt: false };
const NEITHER = { tts: false, stt: false };

describe("what the sidebar says about voice", () => {
  it("on, with a microphone: says so and names the language it listens for", () => {
    expect(voiceStatus(true, "English (Australia)", CHROME)).toEqual({
      live: true,
      title: "Voice is on",
      detail: "English (Australia)",
    });
  });

  it("switched off: says off, whatever the browser could have done", () => {
    for (const caps of [CHROME, FIREFOX, NEITHER]) {
      const status = voiceStatus(false, "English (Australia)", caps);
      expect(status.live).toBe(false);
      expect(status.title).toBe("Voice is off");
    }
  });

  it("a browser that can speak but not listen is not called on", () => {
    const status = voiceStatus(true, "English (Australia)", FIREFOX);
    expect(status.live).toBe(false);
    expect(status.title).toBe("Read Aloud only");
    // The language is the recogniser's, and there is no recogniser.
    expect(status.detail).not.toMatch(/english/i);
  });

  it("a browser with no speech at all says unavailable, not off", () => {
    const status = voiceStatus(true, "English (Australia)", NEITHER);
    expect(status.live).toBe(false);
    expect(status.title).toBe("Voice unavailable");
  });

  it("only the state with a microphone is live", () => {
    expect(voiceStatus(true, "x", { tts: false, stt: true }).live).toBe(true);
    expect(voiceStatus(true, "x", FIREFOX).live).toBe(false);
  });

  it("never reads like the microphone or the Settings button it sits above", () => {
    // Both are how other controls are found, by people and by the tests.
    const every = [
      voiceStatus(true, "English (Australia)", CHROME),
      voiceStatus(true, "English (Australia)", FIREFOX),
      voiceStatus(true, "English (Australia)", NEITHER),
      voiceStatus(false, "English (Australia)", CHROME),
    ];
    for (const { title, detail } of every) {
      expect(`${title} ${detail}`).not.toMatch(/voice commands|settings/i);
    }
  });
});
