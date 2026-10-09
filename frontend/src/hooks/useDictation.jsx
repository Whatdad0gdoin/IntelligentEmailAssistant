/**
 * Dictation: the browser's speech recogniser, kept running while the user
 * talks, handing each finished phrase to `onText`.
 *
 * Unlike a spoken command (hooks/useSpokenCommand.jsx: one utterance, then
 * stop), dictation is continuous and shows what it is hearing as it goes. The constructor is looked up when the
 * hook runs rather than once at load, so a browser without it simply reports
 * `supported: false` (SR-01) and the caller renders nothing.
 *
 * Audio never reaches our server: the recogniser runs in the browser, and only
 * the recognised text comes back. The browser's own speech service may send it
 * on (Chrome to Google, Edge to Microsoft), which the button says.
 */

import { useCallback, useEffect, useRef, useState } from "react";

function recogniser() {
  if (typeof window === "undefined") return undefined;
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}

const MESSAGES = {
  "not-allowed": "Microphone access was denied. Allow it in your browser to dictate.",
  "service-not-allowed": "Microphone access was denied. Allow it in your browser to dictate.",
  "no-speech": "Nothing was heard. Try again, a little closer to the microphone.",
  "audio-capture": "No microphone was found.",
  network: "Speech recognition needs a network connection in this browser.",
};

export function useDictation({ lang, onText }) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState(null);
  const active = useRef(null);
  // The latest callback, so a phrase lands in the current draft, not the one
  // that was on screen when dictation started.
  const deliver = useRef(onText);
  deliver.current = onText;

  const Recognition = recogniser();
  const supported = Boolean(Recognition);

  /** Stop listening and deliver what was already said. */
  const stop = useCallback(() => {
    active.current?.stop();
  }, []);

  /** Stop at once and drop anything still on its way: the draft it was for is gone. */
  const cancel = useCallback(() => {
    const recognition = active.current;
    active.current = null;
    if (recognition) recognition.abort();
    setListening(false);
    setInterim("");
  }, []);

  useEffect(() => () => {
    const recognition = active.current;
    active.current = null;
    recognition?.abort();
  }, []);

  const start = useCallback(() => {
    const Ctor = recogniser();
    if (!Ctor || active.current) return;
    const recognition = new Ctor();
    // From Settings (en-AU unless changed), never navigator.language: that is
    // the browser's menu language, not the language being spoken.
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      if (active.current !== recognition) return;
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript || "";
        if (result.isFinal) {
          if (text.trim()) deliver.current(text.trim());
        } else {
          pending += text;
        }
      }
      setInterim(pending.trim());
    };
    recognition.onerror = (event) => {
      if (active.current !== recognition || event.error === "aborted") return;
      setError(MESSAGES[event.error] || `Speech recognition failed (${event.error}).`);
    };
    recognition.onend = () => {
      if (active.current !== recognition) return;
      active.current = null;
      setListening(false);
      setInterim("");
    };

    active.current = recognition;
    setError(null);
    setInterim("");
    setListening(true);
    try {
      recognition.start();
    } catch {
      active.current = null;
      setListening(false);
      setError("Dictation could not start. Try again.");
    }
  }, [lang]);

  return { supported, listening, interim, error, start, stop, cancel };
}
