/**
 * Voice Commands view (FR-05, spec section 6.3). Calls POST /api/voice/intent.
 *
 * Recognition runs in the browser; only the transcript is sent. The audio never
 * reaches the server, which is why no audio format appears anywhere in this
 * codebase.
 *
 * Section 6.3 is explicit about the failure mode and it is implemented here
 * rather than papered over: on `unknown`, or on confidence below the backend's
 * threshold, the app does NOT dispatch a best guess. It shows the transcript
 * back and asks the user to pick. Acting on a low-confidence intent is how a
 * voice feature ends up summarising the wrong email.
 *
 * Response: { intent, target_email_id, confidence }
 */

import { useEffect, useRef, useState } from "react";
import { ChevronRight, Mic, Square } from "lucide-react";

import * as api from "../api/client.js";

// Mirrors INTENT_CONFIDENCE_THRESHOLD in backend/.env.example. Below this the
// UI asks instead of acting.
const CONFIDENCE_FLOOR = 0.6;

const ACTION_LABEL = {
  summarise: "Summarise it",
  read: "Read it aloud",
  draft: "Draft a reply",
};

const Recognition =
  typeof window !== "undefined"
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : undefined;

export default function Voice({ emails, onRun, onBack }) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const recognitionRef = useRef(null);

  const supported = Boolean(Recognition);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  const send = async (text, alternatives = []) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      // Sender names and subjects go with the transcript so the backend can
      // resolve "the one from Sarah" onto a real id deterministically. Ids are
      // parsed data and never go near the model.
      const payload = await api.voiceIntent(
        text,
        emails.map((e) => ({ id: e.apiId, sender_name: e.from, subject: e.subject })),
        alternatives
      );
      setResult(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const start = () => {
    if (!supported || listening) return;
    const recognition = new Recognition();
    // Locale matters more than anything else here: the default is the browser
    // UI language, and a US model mis-hears Australian vowels constantly.
    recognition.lang = navigator.language || "en-AU";
    recognition.interimResults = false;
    // The engine ranks its guesses, and the top one is often not the one that
    // contains the name. Asking for several lets the backend pick whichever
    // alternative actually resolves to an email in this inbox, which is a far
    // stronger signal than the engine's own confidence.
    recognition.maxAlternatives = 5;

    recognition.onresult = (event) => {
      const results = event.results[0];
      const alternatives = [];
      for (let i = 0; i < results.length; i += 1) {
        const text = results[i].transcript.trim();
        if (text) alternatives.push(text);
      }
      const heard = alternatives[0] || "";
      setTranscript(heard);
      send(heard, alternatives);
    };
    recognition.onerror = (event) => {
      setError(
        event.error === "not-allowed"
          ? "Microphone access was denied. Allow it in your browser to use voice commands."
          : `Speech recognition failed (${event.error}).`
      );
      setListening(false);
    };
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    setTranscript("");
    setResult(null);
    setError(null);
    setListening(true);
    recognition.start();
  };

  const stop = () => {
    recognitionRef.current?.stop();
    setListening(false);
  };

  const target = result?.target_email_id
    ? emails.find((e) => e.apiId === result.target_email_id)
    : null;

  const confident = result && result.intent !== "unknown" && result.confidence >= CONFIDENCE_FLOOR;

  return (
    <div className="feature-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>Voice Commands</span>
      </div>

      <header className="feature-head">
        <div className="feature-icon"><Mic size={22} strokeWidth={2.2} /></div>
        <div>
          <h1 className="main-title">Voice Commands</h1>
          <p className="main-sub">
            Say something like “summarise the email from Sarah”. Your voice is processed
            in the browser - only the text is sent.
          </p>
        </div>
      </header>

      {!supported ? (
        <div className="feature-error">
          <b>This browser has no speech recognition.</b>
          <span>Voice commands need the Web Speech API - Chrome or Edge support it today.</span>
        </div>
      ) : (
        <button
          className={`mic-btn ${listening ? "on" : ""}`}
          onClick={listening ? stop : start}
          disabled={busy}
        >
          {listening ? <><Square size={18} strokeWidth={2.4} /> Stop listening</> : <><Mic size={18} strokeWidth={2.2} /> Start listening</>}
        </button>
      )}

      {listening && <p className="feature-hint listening">Listening…</p>}
      {busy && <p className="feature-hint">Working out what you meant…</p>}

      {transcript && (
        <div className="transcript">
          <span className="transcript-label">Heard</span>
          <p>“{transcript}”</p>
        </div>
      )}

      {error && <div className="feature-error"><b>Voice command failed.</b><span>{error}</span></div>}

      {result && (
        confident ? (
          <div className="feature-card">
            <p className="intent-line">
              <b>{ACTION_LABEL[result.intent] ?? result.intent}</b>
              {target ? <> - “{target.subject}”</> : <> - no specific email matched</>}
              <span className="intent-conf">{Math.round(result.confidence * 100)}% confidence</span>
            </p>
            <button
              className="primary-btn"
              onClick={() => {
                if (!onRun(result.intent, result.target_email_id ?? null)) {
                  setError("I could not tell which email you meant. Open one first, then try again.");
                }
              }}
            >
              Do it
            </button>
          </div>
        ) : (
          /* Section 6.3: show the transcript back and let the user choose. */
          <div className="feature-card">
            <p className="intent-line">
              {result.intent === "unknown"
                ? "I couldn't tell what you wanted."
                : <>I'm not confident enough to act on that ({Math.round(result.confidence * 100)}%).</>}
              {" "}Pick one:
            </p>
            <div className="reader-actions">
              {Object.entries(ACTION_LABEL).map(([intent, label]) => (
                <button
                  key={intent}
                  className="action-btn"
                  onClick={() => {
                    if (!onRun(intent, result?.target_email_id ?? null)) {
                      setError("I could not tell which email you meant. Open one first, then try again.");
                    }
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )
      )}
    </div>
  );
}
