/* Extracted from InboxIQ.jsx. Markup and classes unchanged.

   The AI buttons used to call onAction, which showed a "not functional yet"
   toast for all five. Four of them now open the feature that does the work,
   with this email already selected. Only Tone & Translate still raises the
   toast, because FR-06/FR-07 have no endpoint behind them.

   `soon` on each action is the same flag the sidebar reads, taken from the same
   FEATURES table, so a button here and a nav item there cannot disagree about
   whether something is built. */
import {
  MessageSquareReply, Mic, Paperclip, SlidersHorizontal, Sparkles, Volume2,
} from "lucide-react";

import { CATEGORIES, FEATURES } from "../lib/constants.js";

const isSoon = (id) => Boolean(FEATURES.find((f) => f.id === id)?.soon);

export const MAIL_ACTIONS = [
  { id: "summarise", label: "Summarise", icon: Sparkles },
  { id: "speak", label: "Read Aloud", icon: Volume2 },
  { id: "reply", label: "Draft Reply", icon: MessageSquareReply },
  { id: "tone", label: "Tone & Translate", icon: SlidersHorizontal },
  { id: "voice", label: "Voice Reply", icon: Mic },
];

export default function ReadingPane({ email, onClose, onFeature, onUnavailable }) {
  const cat = CATEGORIES.find((c) => c.key === email.cat);

  // Selecting the email is the caller's job (the row click already did it), so
  // opening a feature is just a view change.
  const open = (id, label) => (isSoon(id) ? onUnavailable(label) : onFeature(id));

  return (
    <div className="reader" key={email.id}>
      {/* Action toolbar */}
      <div className="reader-toolbar">
        <span className="reader-toolbar-label">
          <Sparkles size={14} strokeWidth={2.2} /> AI tools
        </span>
        <div className="reader-actions">
          {MAIL_ACTIONS.map((a) => {
            const AI = a.icon;
            return (
              <button
                key={a.id}
                className={`action-btn ${isSoon(a.id) ? "is-soon" : ""}`}
                onClick={() => open(a.id, a.label)}
              >
                <AI size={15} strokeWidth={2.2} />
                <span>{a.label}</span>
                {isSoon(a.id) && <span className="nav-soon">soon</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* Email header */}
      <div className="reader-head">
        <h2 className="reader-subject">{email.subject}</h2>
        <div className="reader-meta">
          <span className="mail-avatar lg" style={{ background: cat.color }}>{email.initials}</span>
          <div className="reader-sender">
            <span className="reader-from">{email.from}</span>
            <span className="reader-addr">{email.email}</span>
          </div>
          <div className="reader-right">
            <span className="cat-tag" style={{ "--c": cat.color }}><span className="cat-dot" /> {cat.label}</span>
            <span className="reader-time">{email.time}</span>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="reader-body">
        {email.body.split("\n").map((line, i) =>
          line.trim() === "" ? <br key={i} /> : <p key={i}>{line}</p>
        )}
        {email.attach && (
          <div className="reader-attach">
            <Paperclip size={15} /> <span>1 attachment</span>
            <span className="attach-chip">report-draft.pdf</span>
          </div>
        )}
      </div>

      {/* Footer reply bar */}
      <div className="reader-foot">
        <button className="reply-btn" onClick={() => onFeature("reply")}>
          <MessageSquareReply size={16} strokeWidth={2.2} /> Reply
        </button>
        <button className="reply-btn ghost" onClick={() => onFeature("speak")}>
          <Volume2 size={16} strokeWidth={2.2} /> Read Aloud
        </button>
      </div>
    </div>
  );
}
