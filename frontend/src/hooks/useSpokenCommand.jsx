/**
 * One spoken command (FR-05): the browser's speech recogniser run for a single
 * utterance, handing what it heard to `onHeard`.
 *
 * The recogniser ranks several guesses for one utterance, and the top one is
 * often not the one that caught a name. All of them are passed on, best first,
 * so the backend can pick whichever resolves to an email in this inbox, which
 * is a far stronger signal than the engine's own confidence.
 *
 * Unlike dictation (hooks/useDictation.jsx) this listens once and stops, and
 * reports nothing until the utterance is finished. The constructor is looked
 * up when the hook runs rather than once at load, so a browser without it
 * simply reports `supported: false` (SR-01) and the caller shows no microphone.
 *
 * Audio never reaches our server: the recogniser runs in the browser and only
 * the recognised text comes back. The browser's own speech service may send
 * the audio on (Chrome to Google, Edge to Microsoft), which the command bar
 * and Settings both say.
 */

import { useCallback, useEffect, useRef, useState } from "react";

function recogniser() {
  if (typeof window === "undefined") return undefined;
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}

const DENIED = "Microphone access was denied. Allow it in your browser to speak a command.";

const MESSAGES = {
  "not-allowed": DENIED,
  "service-not-allowed": DENIED,
  "no-speech": "Nothing was heard. Try again, a little closer to the microphone.",
  "audio-capture": "No microphone was found.",
  network: "Speech recognition needs a network connection in this browser.",
};

export function useSpokenCommand({ lang, onHeard }) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState(null);
  const active = useRef(null);
  // The latest callback, so what was heard goes to the bar as it is now.
  const deliver = useRef(onHeard);
  deliver.current = onHeard;

  const supported = Boolean(recogniser());

  /** Stop listening; the recogniser still reports what it has heard so far. */
  const stop = useCallback(() => {
    active.current?.stop();
  }, []);

  /** Stop at once and drop anything still on its way. */
  const cancel = useCallback(() => {
    const recognition = active.current;
    active.current = null;
    if (recognition) recognition.abort();
    setListening(false);
  }, []);

  const clearError = useCallback(() => setError(null), []);

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
    // the browser's menu language, so an Indonesian Chrome would hand the
    // recogniser id-ID for a command spoken in English.
    recognition.lang = lang;
    recognition.interimResults = false;
    recognition.maxAlternatives = 5;

    recognition.onresult = (event) => {
      if (active.current !== recognition) return;
      const guesses = event.results[0] || [];
      const alternatives = [];
      for (let i = 0; i < guesses.length; i += 1) {
        const text = (guesses[i]?.transcript || "").trim();
        if (text && !alternatives.includes(text)) alternatives.push(text);
      }
      // One utterance is all this listens for, so it is finished here whether
      // or not the browser has got round to saying so.
      active.current = null;
      setListening(false);
      if (alternatives.length > 0) deliver.current(alternatives[0], alternatives);
    };
    recognition.onerror = (event) => {
      if (active.current !== recognition || event.error === "aborted") return;
      setError(MESSAGES[event.error] || `Speech recognition failed (${event.error}).`);
    };
    recognition.onend = () => {
      if (active.current !== recognition) return;
      active.current = null;
      setListening(false);
    };

    active.current = recognition;
    setError(null);
    setListening(true);
    try {
      recognition.start();
    } catch {
      active.current = null;
      setListening(false);
      setError("Listening could not start. Try again.");
    }
  }, [lang]);

  return { supported, listening, error, start, stop, cancel, clearError };
}
