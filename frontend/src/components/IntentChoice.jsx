/**
 * "Ask, never guess" (FR-05, spec section 6.3), for a command typed or spoken
 * into the command bar.
 *
 * When POST /api/voice/intent answers `unknown`, or answers with confidence
 * below the floor, the bar does not act. It shows this card instead: what the
 * app made of the command (nothing, or not enough) and one button per action,
 * so the user picks rather than the app guessing. Acting on a low-confidence
 * intent is how a command ends up summarising the wrong email.
 *
 * The floor, the wording, the buttons and the "which email?" message live here
 * so the spoken and the typed path cannot drift apart: a command asks the same
 * question at the same threshold however it reached the bar.
 */

import { useId } from "react";

// Mirrors INTENT_CONFIDENCE_THRESHOLD in backend/.env.example. Below this the
// UI asks instead of acting.
export const CONFIDENCE_FLOOR = 0.6;

export const ACTION_LABEL = {
  summarise: "Summarise it",
  read: "Read it aloud",
  draft: "Draft a reply",
};

// Shown when an action has no email to act on: none was named and none is
// open. Section 6.3 says ask, so nothing falls back to "the first email".
export const NO_TARGET_MESSAGE = "I could not tell which email you meant. Open one first, then try again.";

/**
 * True when a result is safe to act on without asking: an action the reading
 * pane knows, at or above the floor. Anything else, including a missing
 * confidence, is a question for the user.
 */
export function isConfident(result) {
  return (
    Boolean(result) &&
    Object.keys(ACTION_LABEL).includes(result.intent) &&
    result.confidence >= CONFIDENCE_FLOOR
  );
}

/**
 * Dashboard's candidate list in the shape the intent route reads. The order is
 * kept as given: Dashboard sorts it newest first, and the backend resolves
 * "the latest email" to the first entry. Ids are parsed data and never reach
 * the model; the backend matches names and subjects against them itself.
 */
export function intentCandidates(emails) {
  return emails.map((e) => ({
    id: e.apiId,
    sender_name: e.from,
    subject: e.subject,
    received_at: e.receivedAt,
  }));
}

/**
 * The question itself. `children` render above it, which is where the command
 * bar shows back what was typed or heard. Cancel appears only when the caller
 * passes `onCancel`.
 */
export default function IntentChoice({ result, onChoose, onCancel, children }) {
  const promptId = useId();
  return (
    <div className="feature-card" role="group" aria-labelledby={promptId}>
      {children}
      <p className="intent-line" id={promptId}>
        {result.intent === "unknown"
          ? "I couldn't tell what you wanted."
          : <>I'm not confident enough to act on that ({Math.round(result.confidence * 100)}%).</>}
        {" "}Pick one:
      </p>
      <div className="reader-actions">
        {Object.entries(ACTION_LABEL).map(([intent, label]) => (
          <button key={intent} type="button" className="action-btn" onClick={() => onChoose(intent)}>
            {label}
          </button>
        ))}
        {onCancel && (
          <button type="button" className="choice-cancel" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
