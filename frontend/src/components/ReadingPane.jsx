/* Extracted from InboxIQ.jsx. Markup and classes unchanged.

   The AI action buttons currently call onAction, which shows the teammate's
   "not functional yet" toast. They are wired to real endpoints in steps 5, 6
   and 8; until then they must keep telling the truth about not working. */
import {
  MessageSquareReply, Mic, Paperclip, SlidersHorizontal, Sparkles, Volume2,
} from "lucide-react";

import { CATEGORIES } from "../lib/constants.js";

export const MAIL_ACTIONS = [
  { id: "summarise", label: "Summarise", icon: Sparkles },
  { id: "speak", label: "Read Aloud", icon: Volume2 },
  { id: "reply", label: "Draft Reply", icon: MessageSquareReply },
  { id: "tone", label: "Tone & Translate", icon: SlidersHorizontal },
  { id: "voice", label: "Voice Reply", icon: Mic },
];


export default function ReadingPane({ email, onClose, onAction }) {
  const cat = CATEGORIES.find((c) => c.key === email.cat);
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
              <button key={a.id} className="action-btn" onClick={() => onAction(a.label)}>
                <AI size={15} strokeWidth={2.2} />
                <span>{a.label}</span>
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

      {/* Footer reply bar (non-functional) */}
      <div className="reader-foot">
        <button className="reply-btn" onClick={() => onAction("Draft Reply")}>
          <MessageSquareReply size={16} strokeWidth={2.2} /> Reply
        </button>
        <button className="reply-btn ghost" onClick={() => onAction("Read Aloud")}>
          <Volume2 size={16} strokeWidth={2.2} /> Read Aloud
        </button>
      </div>
    </div>
  );
}
