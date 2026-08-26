/**
 * Browser capability detection (SR-01).
 *
 * Voice is a Chrome/Edge feature. Firefox and Safari must degrade gracefully,
 * never crash, and every voice action must have a click equivalent -- so this
 * is read once at load and the UI adapts around it rather than calling into
 * APIs that may not exist.
 */

function has(getter) {
  try {
    return Boolean(getter());
  } catch {
    // Some privacy modes throw on access rather than returning undefined.
    return false;
  }
}

export const capabilities = {
  /** speechSynthesis: text to speech (FR-04). */
  tts: has(() => typeof window !== "undefined" && window.speechSynthesis),

  /** SpeechRecognition: speech to text (FR-05). Prefixed in Chrome/Edge. */
  stt: has(
    () =>
      typeof window !== "undefined" &&
      (window.SpeechRecognition || window.webkitSpeechRecognition)
  ),
};

export const voiceFullySupported = capabilities.tts && capabilities.stt;

/** Human-readable reason for the persistent notice, or null when all is well. */
export function voiceLimitation() {
  if (voiceFullySupported) return null;
  if (!capabilities.tts && !capabilities.stt) {
    return "Voice is unavailable in this browser. Every feature remains usable by clicking.";
  }
  if (!capabilities.stt) {
    return "Voice commands are unavailable in this browser. Read Aloud still works, and every feature remains usable by clicking.";
  }
  return "Read Aloud is unavailable in this browser. Every feature remains usable by clicking.";
}
