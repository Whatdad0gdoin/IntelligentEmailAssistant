/**
 * Read Aloud, on the browser's speech synthesis.
 *
 * There is no backend involved and there should not be: the text is already on
 * the client, and sending it away to be spoken would put email content on a
 * third-party service for no gain (NFR-03).
 *
 * `supported` is reported rather than assumed. speechSynthesis is missing or
 * disabled often enough (older browsers, some Linux builds with no installed
 * voice) that the UI needs to say so instead of running a dead button.
 */
import { useCallback, useEffect, useState } from "react";

const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;

export default function useSpeech() {
  const supported = Boolean(synth);
  const [speaking, setSpeaking] = useState(false);

  // Leaving an utterance running after the component unmounts means the voice
  // keeps talking over whatever the user navigated to.
  useEffect(() => () => { if (synth) synth.cancel(); }, []);

  const stop = useCallback(() => {
    if (!synth) return;
    synth.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback((text) => {
    if (!synth || !text) return;
    synth.cancel();                     // never queue on top of a running one
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(utterance);
  }, []);

  return { supported, speaking, speak, stop };
}
