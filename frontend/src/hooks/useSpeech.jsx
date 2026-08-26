/**
 * Text to speech for summaries (FR-04).
 *
 * Reads the summary sentences, never the raw email body -- the point of the
 * feature is to consume the brief, and the body may be long, quoted or HTML.
 *
 * ---------------------------------------------------------------------------
 * WHY THE DEFAULT SOUNDS ROBOTIC, AND WHAT THIS DOES ABOUT IT
 *
 * Calling speechSynthesis.speak() with no voice set uses the platform default,
 * which on Windows is a 1990s-era formant synthesiser (Microsoft David/Zira
 * Desktop) and on Linux is eSpeak. Those are the robot voices. Modern browsers
 * also ship neural voices that sound close to human, but you only get one if
 * you ask for it by name.
 *
 * Three fixes, in order of how much they matter:
 *
 * 1. PICK A NEURAL VOICE. Neural voices are server-side and report
 *    `localService === false`; on Edge/Windows they are named "... Online
 *    (Natural)", on Chrome "Google ...". VOICE_PREFERENCE below ranks them.
 *
 * 2. WAIT FOR THE VOICE LIST. getVoices() returns [] on first call in Chrome
 *    and Edge -- the list populates asynchronously and fires `voiceschanged`.
 *    Code that reads it once at module load gets an empty array, silently falls
 *    back to the default robot, and looks like it "just sounds bad". This is
 *    the single most common cause and it is a race, so it can appear to work on
 *    a warm reload and fail on a cold one.
 *
 * 3. SPEAK SENTENCE BY SENTENCE. Chrome truncates or stalls on long utterances
 *    (the ~15 second / ~300 character bug). Queuing one utterance per sentence
 *    avoids it and, as a bonus, produces a natural pause at each full stop
 *    instead of one breathless run-on. FR-01 already hands us an array of
 *    sentences, so this costs nothing.
 *
 * Rate is nudged slightly below 1.0: neural voices read a touch fast for
 * comprehension when the listener is not looking at the screen.
 * ---------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { capabilities } from "../lib/capabilities.js";

/** Ranked substrings; the first match wins. Highest quality first. */
const VOICE_PREFERENCE = [
  "Natural",        // Edge/Windows 11 neural, e.g. "Microsoft Aria Online (Natural)"
  "Online",         // Edge cloud voices generally
  "Google US English",
  "Google UK English Female",
  "Google",         // any remaining Google neural voice on Chrome
  "Samantha",       // macOS/iOS, markedly better than the Windows desktop voices
  "Zira",           // last resort local Windows voice, still better than David
];

export const SPEECH_RATE = 0.95;
export const SPEECH_PITCH = 1.0;

/** Resolves once the browser has actually populated its voice list. */
function loadVoices() {
  return new Promise((resolve) => {
    if (!capabilities.tts) {
      resolve([]);
      return;
    }
    const existing = window.speechSynthesis.getVoices();
    if (existing.length > 0) {
      resolve(existing);
      return;
    }
    // Cold start: the list is not ready yet. Wait for the event, but do not
    // wait forever -- some browsers never fire it if there are no voices.
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.speechSynthesis.removeEventListener("voiceschanged", finish);
      resolve(window.speechSynthesis.getVoices());
    };
    window.speechSynthesis.addEventListener("voiceschanged", finish);
    setTimeout(finish, 1500);
  });
}

/** Best available English voice, or null to accept the platform default. */
export function pickVoice(voices) {
  const english = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith("en"));
  const pool = english.length > 0 ? english : voices;
  if (pool.length === 0) return null;

  for (const wanted of VOICE_PREFERENCE) {
    const hit = pool.find((v) => v.name.includes(wanted));
    if (hit) return hit;
  }
  // Nothing matched by name: prefer any network voice, which is neural far
  // more often than not.
  return pool.find((v) => v.localService === false) || pool[0];
}

export function useSpeech() {
  const [speakingId, setSpeakingId] = useState(null);
  const [voice, setVoice] = useState(null);
  const cancelled = useRef(false);

  useEffect(() => {
    let alive = true;
    loadVoices().then((voices) => {
      if (alive) setVoice(pickVoice(voices));
    });
    return () => {
      alive = false;
    };
  }, []);

  const stop = useCallback(() => {
    if (!capabilities.tts) return;
    cancelled.current = true;
    // cancel() genuinely discards the queue rather than pausing it (section 6.2).
    window.speechSynthesis.cancel();
    setSpeakingId(null);
  }, []);

  const speak = useCallback(
    (sentences, id) => {
      if (!capabilities.tts) return;

      window.speechSynthesis.cancel();
      cancelled.current = false;

      const parts = (Array.isArray(sentences) ? sentences : [String(sentences ?? "")])
        .map((s) => String(s).trim())
        .filter(Boolean);
      if (parts.length === 0) return;

      setSpeakingId(id ?? "default");

      parts.forEach((text, index) => {
        const utterance = new SpeechSynthesisUtterance(text);
        if (voice) utterance.voice = voice;
        utterance.rate = SPEECH_RATE;
        utterance.pitch = SPEECH_PITCH;
        utterance.volume = 1;

        // Only the final sentence clears the speaking state, so the button
        // stays in "Stop" for the whole read rather than flickering per part.
        if (index === parts.length - 1) {
          utterance.onend = () => {
            if (!cancelled.current) setSpeakingId(null);
          };
        }
        utterance.onerror = () => setSpeakingId(null);

        window.speechSynthesis.speak(utterance);
      });
    },
    [voice]
  );

  const toggle = useCallback(
    (sentences, id) => {
      if (speakingId === (id ?? "default")) stop();
      else speak(sentences, id);
    },
    [speakingId, speak, stop]
  );

  // Leaving the page mid-sentence would otherwise keep the browser talking.
  useEffect(() => () => {
    if (capabilities.tts) window.speechSynthesis.cancel();
  }, []);

  return {
    speak,
    stop,
    toggle,
    speakingId,
    supported: capabilities.tts,
    /** Exposed so Settings can show which voice is actually in use. */
    voiceName: voice ? voice.name : null,
    isNeural: voice ? voice.localService === false : false,
  };
}
