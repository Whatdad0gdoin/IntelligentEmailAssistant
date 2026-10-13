/**
 * Command bar: give the assistant an instruction, typed or spoken (FR-05, spec
 * section 6.3).
 *
 * The bar is shown in every browser, whether or not voice is switched on,
 * because typing needs neither a microphone nor a recogniser. Where the
 * browser can recognise speech (Chrome, Edge) and voice is on in Settings, the
 * bar also has a microphone. This is the only place a command is spoken: there
 * is no separate voice page.
 *
 * Speaking fills the field; it does not run anything. What the recogniser
 * heard is put in the field, where a mishearing can be seen and fixed, and the
 * command runs when the user presses Run, exactly as a typed one does. That
 * pause is deliberate: a recogniser mishears, and a command it misheard should
 * not act on someone's email before they have read it back. If the text is
 * sent as it was heard, the recogniser's other guesses go with it, so the
 * backend can match a name the top guess missed; once the text is edited it is
 * a typed command and they are dropped.
 *
 * It adds no second interpreter. Typed or spoken, the text goes to POST
 * /api/voice/intent with the same newest-first candidates Dashboard builds,
 * and the result is dispatched through the same runVoiceAction: the target
 * opens and the reading pane runs the action. Typed, spoken and clicked all
 * end in the same code, so "read" in a browser that cannot speak degrades to a
 * summary on screen.
 *
 * Section 6.3 holds unchanged. On `unknown`, or below the confidence floor,
 * the bar shows the command back and asks (IntentChoice). A confident command
 * runs at once.
 *
 * Our server never receives audio, only the text recognised from it. The
 * browser's speech service may, and the bar says so while it listens; Settings
 * says it in full.
 *
 * The bar is a band across the top of the page with the microphone as its
 * largest control. Under the field it shows one row: what it is doing or has
 * just done, or, when it has nothing to say, a few example commands. An
 * example fills the field like a spoken command does and runs nothing until
 * Run is pressed.
 */

import { useRef, useState } from "react";
import { CornerDownLeft, Loader2, Mic, Sparkles, Square } from "lucide-react";

import * as api from "../api/client.js";
import { useSpokenCommand } from "../hooks/useSpokenCommand.jsx";
import { DEFAULT_SPEECH_LANG } from "../lib/constants.js";
import IntentChoice, { NO_TARGET_MESSAGE, intentCandidates, isConfident } from "./IntentChoice.jsx";

// The intent route reads at most this many characters of a transcript
// (MAX_TRANSCRIPT_CHARS in backend/routes/voice.py). The field stops at the
// same length, so the end of a long command is never dropped without a sign.
const MAX_CHARS = 500;

// An empty or unreadable reply is a question for the user, never an action.
const UNKNOWN = { intent: "unknown", target_email_id: null, confidence: 0 };

export const LISTENING_HINT =
  "Listening… say a command. Our server never receives your audio; your browser's speech service may.";
export const HEARD_HINT = "That is what was heard. Fix it if it is wrong, then press Run.";

// Examples that work whatever is open: "the latest email" resolves to the
// first candidate (backend/orchestrator/intent.py). Only summarise, read and
// draft are intents, so nothing else is suggested. Reading aloud is offered
// only where the browser can speak and voice is on.
export const EXAMPLES = ["Summarise the latest email", "Draft a reply to the latest email"];
export const READ_EXAMPLE = "Read the latest email aloud";

// The moving bars shown in the field while it listens. They say the microphone
// is open; they are not a level meter, because the recogniser reports no
// volume. Heights and delays are fixed, so the pattern is the same every time.
const WAVE = Array.from({ length: 64 }, (_, i) => ({
  height: 8 + Math.round(22 * Math.abs(Math.sin(i * 0.9))),
  animationDelay: `${((i * 37) % 11) / 10}s`,
}));

export default function CommandBar({
  emails,
  onRun,
  voice = false,
  readAloud = false,
  speechLang = DEFAULT_SPEECH_LANG,
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // A command the app will not act on alone: { command, spoken, result }.
  const [question, setQuestion] = useState(null);
  // What the last command did. Shown under the field and announced, because
  // focus stays in the field while the reading pane changes elsewhere.
  const [outcome, setOutcome] = useState("");
  // What the microphone last put in the field: { text, alternatives }. It
  // counts as spoken only while the field still holds exactly that text.
  const [heard, setHeard] = useState(null);

  const inputRef = useRef(null);
  const inFlight = useRef(false);
  // The request takes a moment and the user may open another email meanwhile,
  // so the reply is dispatched through the newest onRun, not the one captured
  // when Enter was pressed.
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;

  const spoken = useSpokenCommand({
    lang: speechLang,
    onHeard: (top, alternatives) => {
      const said = top.slice(0, MAX_CHARS);
      setHeard({ text: said, alternatives });
      setText(said);
      setQuestion(null);
      setError(null);
      setOutcome("");
      // The next thing to do is read it and press Enter, so focus goes there.
      inputRef.current?.focus();
    },
  });
  const micShown = voice && spoken.supported;

  const command = text.trim();
  const asHeard = heard !== null && heard.text.trim() === command && command !== "";

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
    setHeard(null);
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
    // The command is going as it stands; anything still being said is not
    // part of it.
    spoken.cancel();
    setBusy(true);
    setError(null);
    setQuestion(null);
    setOutcome("");
    try {
      const candidates = intentCandidates(emails);
      const reply = asHeard
        ? await api.voiceIntent(command, candidates, heard.alternatives)
        : await api.voiceIntent(command, candidates);
      const result = reply || UNKNOWN;
      if (isConfident(result)) dispatch(result.intent, result.target_email_id);
      else setQuestion({ command, spoken: asHeard, result });
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

  // A command already on its way is not interrupted by a new one being spoken.
  const toggleMic = () => {
    if (spoken.listening) spoken.stop();
    else if (!inFlight.current) spoken.start();
  };

  // An example goes into the field as a typed command and waits for Run, so
  // it can be changed first. With no email to name there is nothing to try.
  let examples = [];
  if (emails.length > 0) {
    examples = readAloud ? [EXAMPLES[0], READ_EXAMPLE, EXAMPLES[1]] : EXAMPLES;
  }
  const fillExample = (example) => {
    setText(example);
    setHeard(null);
    setQuestion(null);
    setError(null);
    setOutcome("");
    spoken.clearError();
    inputRef.current?.focus();
  };

  let hint = outcome;
  if (busy) hint = "Working out what you meant…";
  else if (spoken.listening) hint = LISTENING_HINT;
  else if (asHeard && !question && !error) hint = HEARD_HINT;

  const failure = error
    ? { title: "Command failed.", message: error }
    : spoken.error
      ? { title: "Could not listen.", message: spoken.error }
      : null;

  return (
    <div className="command-bar" onKeyDown={onKeyDown}>
      <div className="command-band">
        <form className="command-row" onSubmit={submit} aria-busy={busy}>
          {/* Only where it can work (SR-01): a recogniser in this browser, and
              voice switched on. type="button", or pressing it would submit. */}
          {micShown && (
            <button
              type="button"
              className={`command-mic ${spoken.listening ? "on" : ""}`}
              onClick={toggleMic}
              aria-pressed={spoken.listening}
              aria-label={spoken.listening ? "Stop listening" : "Speak a command"}
              aria-disabled={busy || undefined}
              title="Speak a command. Our server never receives your audio; your browser's speech service may."
            >
              {spoken.listening
                ? <Square size={18} strokeWidth={2.6} fill="currentColor" aria-hidden="true" />
                : <Mic size={24} strokeWidth={2.2} aria-hidden="true" />}
            </button>
          )}
          <div className={`command-field ${spoken.listening ? "listening" : ""}`}>
            {/* Without a microphone the field keeps a mark of its own. */}
            {!micShown && <Sparkles size={16} strokeWidth={2.2} className="command-icon" aria-hidden="true" />}
            <input
              ref={inputRef}
              type="text"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                setOutcome("");
                spoken.clearError();
              }}
              placeholder={spoken.listening
                ? "Listening…"
                : micShown
                  ? "Type or say a command, e.g. summarise the latest email"
                  : "Type a command, e.g. summarise the latest email"}
              aria-label="Command"
              maxLength={MAX_CHARS}
              readOnly={busy}
              autoComplete="off"
            />
            {spoken.listening && (
              <span className="command-wave" aria-hidden="true">
                {WAVE.map((bar, i) => <span key={i} style={bar} />)}
              </span>
            )}
            {/* Not disabled while busy: disabling the focused control drops
                focus to the page, and a keyboard user would have to find the
                field again. The in-flight guard in submit is what stops a
                second request. */}
            <button type="submit" className="command-run" disabled={!command} aria-disabled={busy || undefined}>
              {busy
                ? <Loader2 size={14} strokeWidth={2.4} className="spin" aria-hidden="true" />
                : <CornerDownLeft size={14} strokeWidth={2.4} aria-hidden="true" />}
              <span>Run</span>
            </button>
          </div>
        </form>

        <p className="command-hint" aria-live="polite">{hint}</p>

        {/* The row under the field is the line above when it has something to
            say, and these otherwise, so the band keeps its height. */}
        {!hint && examples.length > 0 && (
          <div className="command-examples" role="group" aria-label="Example commands">
            <span className="command-examples-label" aria-hidden="true">Try</span>
            {examples.map((example) => (
              <button className="command-example" type="button" key={example} onClick={() => fillExample(example)}>
                {example}
              </button>
            ))}
          </div>
        )}
      </div>

      {failure && (
        <div className="feature-error" role="alert">
          <b>{failure.title}</b>
          <span>{failure.message}</span>
        </div>
      )}

      {question && (
        <IntentChoice result={question.result} onChoose={choose} onCancel={cancel}>
          <div className="transcript intent-quote">
            <span className="transcript-label">{question.spoken ? "Heard" : "You typed"}</span>
            <p>“{question.command}”</p>
          </div>
        </IntentChoice>
      )}
    </div>
  );
}
