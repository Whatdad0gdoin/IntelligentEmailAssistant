/**
 * Renders the verification result that comes back with every generated text
 * (spec sections 4.4/4.5).
 *
 * The backend never withholds an ungrounded summary and never silently ships
 * one either -- it returns the text *plus* `grounded` and `ungrounded_flags`.
 * The UI has to honour that: an unverified claim is shown, and shown as
 * unverified. Hiding the flags would throw away the whole point of the
 * grounding layer.
 *
 * A flag means "this token is not in the source email", which is evidence of a
 * problem rather than proof of one, so the wording says "check" and not
 * "wrong".
 */
import { CheckCircle2, TriangleAlert } from "lucide-react";

export default function GroundingNotice({ grounded, flags = [] }) {
  if (grounded) {
    return (
      <div className="ground-note ok">
        <CheckCircle2 size={15} strokeWidth={2.2} />
        <span>Every checkable claim was found in the source email.</span>
      </div>
    );
  }

  return (
    <div className="ground-note warn">
      <div className="ground-note-head">
        <TriangleAlert size={15} strokeWidth={2.2} />
        <span>
          {flags.length} claim{flags.length === 1 ? "" : "s"} could not be
          verified against the source email. Check {flags.length === 1 ? "it" : "them"} before you rely on this.
        </span>
      </div>
      {flags.length > 0 && (
        <ul className="ground-flags">
          {flags.map((f, i) => (
            <li key={i}>
              <code>{f.claim}</code> <span>{f.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
