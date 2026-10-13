/**
 * The sidebar's short account of voice: a title, one line of detail, and
 * whether there is a microphone to speak into (`live`).
 *
 * It takes the capabilities rather than importing them. lib/capabilities.js
 * reads `window` once at load, so a test can only change the answer by mocking
 * that module, and a function that lived there would have to be mocked with
 * it. Here every branch is plain input and output.
 *
 * The wording stays clear of two phrases on purpose: "voice commands", which
 * is what a microphone button would be called, and "Settings", which is the
 * button under this one.
 */
export function voiceStatus(enabled, language, caps) {
  if (!enabled) return { live: false, title: "Voice is off", detail: "Commands can still be typed" };
  if (caps.stt) return { live: true, title: "Voice is on", detail: language };
  if (caps.tts) return { live: false, title: "Read Aloud only", detail: "This browser cannot listen" };
  return { live: false, title: "Voice unavailable", detail: "Not supported in this browser" };
}
