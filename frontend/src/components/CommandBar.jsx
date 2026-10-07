/**
 * Command bar: type an instruction instead of saying it (FR-05, spec
 * section 6.3).
 *
 * Voice Commands needs the browser's speech recogniser, so where there is none
 * (Firefox, Safari) SR-01 removes that destination, and with it every way to
 * give the assistant a command. This bar is the typed path. It is shown in
 * every browser, whether or not voice is switched on, because it needs neither
 * a microphone nor a recogniser.
 *
 * It adds no second interpreter. Typed text goes to the same POST
 * /api/voice/intent a transcript does, with the same newest-first candidates
 * Dashboard builds for voice, and the result is dispatched through the same
 * runVoiceAction: the target opens and the reading pane runs the action. Typed,
 * spoken and clicked all end in the same code, so "read" in a browser that
 * cannot speak degrades exactly as the spoken command does, to a summary on
 * screen.
 *
 * Section 6.3 holds unchanged. On `unknown`, or below the confidence floor,
 * the bar shows back what was typed and asks (IntentChoice, shared with the
 * Voice view). A confident command runs at once: the Voice view stops for a
 * "Do it" because the recogniser may have misheard, and typed text has no
 * recognition step to second-guess.
 */

import { useRef, useState } from "react";
import { CornerDownLeft, Loader2, Sparkles } from "lucide-react";

import * as api from "../api/client.js";
import IntentChoice, { NO_TARGET_MESSAGE, intentCandidates, isConfident } from "./IntentChoice.jsx";

// The intent route reads at most this many characters of a transcript
// (MAX_TRANSCRIPT_CHARS in backend/routes/voice.py). The field stops at the
// same length, so the end of a long command is never dropped without a sign.
const MAX_CHARS = 500;

// An empty or unreadable reply is a question for the user, never an action.
const UNKNOWN = { intent: "unknown", target_email_id: null, confidence: 0 };

export default function CommandBar({ emails, onRun }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // A command the app will not act on alone: { typed, result }.
  const [question, setQuestion] = useState(null);
  // What the last command did. Shown under the field and announced, because
  // focus stays in the field while the reading pane changes elsewhere.
  const [outcome, setOutcome] = useState("");

  const inputRef = useRef(null);
  const inFlight = useRef(false);
  // The request takes a moment and the user may open another email meanwhile,
  // so the reply is dispatched through the newest onRun, not the one captured
  // when Enter was pressed.
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;

  const command = text.trim();

  // Hands the action to Dashboard. When there is no email to act on (none was
  // named and none is open) it says so and keeps the command for another try.
  const dispatch = (intent, targetId) => {
    if (!onRunRef.current(intent, targetId ?? null)) {
      setError(NO_TARGET_MESSAGE);
      return false;
    }
    let done = "Working on the open email.";
    if (targetId) {
      const target = emails.find((e) => e.apiId === targetId);
      done = target ? `Opened “${target.subject}”.` : "Opened the email you named.";
    }
    setText("");
    setQuestion(null);
    setError(null);
    setOutcome(done);
    return true;
  };

  const submit = async (event) => {
    event.preventDefault();
    // Whitespace is not a command, and a second Enter while the first is in
    // flight is not a second command.
    if (!command || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setQuestion(null);
    setOutcome("");
    try {
      const result = (await api.voiceIntent(command, intentCandidates(emails))) || UNKNOWN;
      if (isConfident(result)) dispatch(result.intent, result.target_email_id);
      else setQuestion({ typed: command, result });
    } catch (err) {
      setError(err.message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  // The question's buttons disappear once it is answered, so focus returns to
  // the field rather than falling back to the top of the page.
  const cancel = () => {
    setQuestion(null);
    setError(null);
    inputRef.current?.focus();
  };

  const choose = (intent) => {
    if (dispatch(intent, question.result.target_email_id)) inputRef.current?.focus();
  };

  // Escape backs out of the question from anywhere in the bar.
  const onKeyDown = (event) => {
    if (event.key === "Escape" && question) {
      event.preventDefault();
      cancel();
    }
  };

  return (
    <div className="command-bar" onKeyDown={onKeyDown}>
      <form className="command-field" onSubmit={submit} aria-busy={busy}>
        <Sparkles size={16} strokeWidth={2.2} className="command-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setOutcome("");
          }}
          placeholder="Type a command — e.g. summarise the latest email"
          aria-label="Command"
          maxLength={MAX_CHARS}
          readOnly={busy}
          autoComplete="off"
        />
        {/* Not disabled while busy: disabling the focused control drops focus
            to the page, and a keyboard user would have to find the field again.
            The in-flight guard in submit is what stops a second request. */}
        <button type="submit" className="command-run" disabled={!command} aria-disabled={busy || undefined}>
          {busy
            ? <Loader2 size={14} strokeWidth={2.4} className="spin" aria-hidden="true" />
            : <CornerDownLeft size={14} strokeWidth={2.4} aria-hidden="true" />}
          <span>Run</span>
        </button>
      </form>

      <p className="command-hint" aria-live="polite">
        {busy ? "Working out what you meant…" : outcome}
      </p>

      {error && (
        <div className="feature-error" role="alert">
          <b>Command failed.</b>
          <span>{error}</span>
        </div>
      )}

      {question && (
        <IntentChoice result={question.result} onChoose={choose} onCancel={cancel}>
          <div className="transcript intent-quote">
            <span className="transcript-label">You typed</span>
            <p>“{question.typed}”</p>
          </div>
        </IntentChoice>
      )}
    </div>
  );
}
