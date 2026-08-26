/**
 * Reading pane with the AI features rendered IN PLACE.
 *
 * Summarise (FR-01), Read Aloud (FR-04) and Draft Reply (FR-03) all act on the
 * email that is already open and render their output directly beneath the
 * toolbar. Nothing navigates away: losing sight of the message you are acting
 * on is what made the old "go to another screen" flow awkward.
 *
 * Two actions deliberately stay out of this pane:
 *  - Tone and Translate (FR-06/FR-07) is out of scope for this build.
 *  - Voice Commands (FR-05) is inbox-wide, not a property of one email, so it
 *    does not belong on a per-message toolbar.
 */

import { useEffect, useState } from "react";
import {
  Check, Loader2, MessageSquareReply, Sparkles, Square, Volume2, X,
} from "lucide-react";

import * as api from "../api/client.js";
import { useSpeech } from "../hooks/useSpeech.jsx";
import GroundingNotice from "./GroundingNotice.jsx";
import { CATEGORIES } from "../lib/constants.js";
import { segment, toParagraphs } from "../lib/highlight.js";

export default function ReadingPane({ email, body, bodyLoading, pendingAction, onActionConsumed }) {
  const [summary, setSummary] = useState(null);
  const [summaryState, setSummaryState] = useState("idle");
  const [summaryError, setSummaryError] = useState(null);

  const [draft, setDraft] = useState(null);
  const [draftText, setDraftText] = useState("");
  const [draftState, setDraftState] = useState("idle");
  const [draftError, setDraftError] = useState(null);
  const [instruction, setInstruction] = useState("");
  const [approved, setApproved] = useState(false);
  // Which summary sentence the reader is tracing back to the source.
  const [tracedSentence, setTracedSentence] = useState(null);

  const speech = useSpeech();
  const cat = CATEGORIES.find((c) => c.label === email.category);

  // Selecting a different email must not show the previous one's output.
  useEffect(() => {
    setSummary(null);
    setSummaryState("idle");
    setSummaryError(null);
    setDraft(null);
    setDraftText("");
    setDraftState("idle");
    setDraftError(null);
    setInstruction("");
    setApproved(false);
    setTracedSentence(null);
    speech.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email.id]);

  async function runSummarise() {
    if (summaryState === "loading") return null;
    setSummaryState("loading");
    setSummaryError(null);
    try {
      const result = await api.summarise(email.id);
      setSummary(result);
      setSummaryState("idle");
      return result;
    } catch (err) {
      setSummaryError(err.message);
      setSummaryState("error");
      return null;
    }
  }

  async function runDraft() {
    if (draftState === "loading") return;
    setDraftState("loading");
    setDraftError(null);
    setApproved(false);
    try {
      const result = await api.draft(email.id, instruction.trim() || undefined);
      setDraft(result);
      setDraftText(result.draft);
      setDraftState("idle");
    } catch (err) {
      setDraftError(err.message);
      setDraftState("error");
    }
  }

  // Reads the summary, never the raw body (section 6.2). With no summary yet,
  // one is fetched first so the button cannot end up reading email text.
  async function readAloud() {
    if (summary && summary.summary && summary.summary.length > 0) {
      speech.toggle(summary.summary, email.id);
      return;
    }
    const result = await runSummarise();
    if (result && result.summary && result.summary.length > 0) {
      speech.speak(result.summary, email.id);
    }
  }

  // A voice command (FR-05) dispatches here rather than opening a separate
  // screen, so the spoken path and the click path run exactly the same code.
  // SR-01 holds: every one of these is also a button above.
  useEffect(() => {
    if (!pendingAction) return;
    if (pendingAction.emailId && pendingAction.emailId !== email.id) return;
    if (pendingAction.intent === "summarise") runSummarise();
    else if (pendingAction.intent === "read") readAloud();
    else if (pendingAction.intent === "draft") runDraft();
    onActionConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAction, email.id]);

  const speaking = speech.speakingId === email.id;
  const initials = (email.sender_name || email.sender || "?").slice(0, 2).toUpperCase();

  return (
    <div className="reader" key={email.id}>
      <div className="reader-toolbar">
        <span className="reader-toolbar-label">
          <Sparkles size={14} strokeWidth={2.2} /> AI tools
        </span>
        <div className="reader-actions">
          <button className="action-btn" onClick={runSummarise} disabled={summaryState === "loading"}>
            {summaryState === "loading"
              ? <Loader2 size={15} strokeWidth={2.2} className="spin" />
              : <Sparkles size={15} strokeWidth={2.2} />}
            <span>{summary ? "Re-summarise" : "Summarise"}</span>
          </button>

          <button
            className={`action-btn ${speaking ? "on" : ""}`}
            onClick={readAloud}
            disabled={!speech.supported}
            title={speech.supported ? "Reads the summary aloud" : "Not supported in this browser"}
          >
            {speaking ? <Square size={15} strokeWidth={2.4} /> : <Volume2 size={15} strokeWidth={2.2} />}
            <span>{speaking ? "Stop" : "Read Aloud"}</span>
          </button>

          <button className="action-btn" onClick={runDraft} disabled={draftState === "loading"}>
            {draftState === "loading"
              ? <Loader2 size={15} strokeWidth={2.2} className="spin" />
              : <MessageSquareReply size={15} strokeWidth={2.2} />}
            <span>{draft ? "Regenerate" : "Draft Reply"}</span>
          </button>
        </div>
      </div>

      {/* ---------------------------------------------------- summary (FR-01) */}
      {(summary || summaryState === "loading" || summaryError) && (
        <section className="ai-panel">
          <header className="ai-panel-head">
            <Sparkles size={14} strokeWidth={2.4} /> <b>Summary</b>
            {summary && !summary.grounded && <span className="ai-chip warn">Unverified</span>}
            {summary && summary.grounded && <span className="ai-chip ok">Verified</span>}
            <button
              className="ai-close"
              onClick={() => { setSummary(null); setSummaryState("idle"); setSummaryError(null); speech.stop(); }}
              aria-label="Dismiss summary"
            >
              <X size={14} />
            </button>
          </header>

          {summaryState === "loading" && <div className="ai-skel"><span /><span /><span /></div>}
          {summaryError && <p className="ai-error">{summaryError}</p>}

          {summary && (
            <>
              <GroundingNotice grounded={summary.grounded} flags={summary.ungrounded_flags} />
              <ol className="ai-summary">
                {summary.summary.map((s, i) => {
                  const entry = summary.provenance
                    ? summary.provenance.find((pv) => pv.sentence === i)
                    : null;
                  const supported = entry && entry.spans && entry.spans.length > 0;
                  const active = tracedSentence === i;
                  return (
                    <li key={i}>
                      <button
                        type="button"
                        className={`trace ${active ? "on" : ""} ${supported ? "" : "unsupported"}`}
                        onClick={() => setTracedSentence(active ? null : i)}
                        title={supported ? "Show the passage this came from" : "No supporting passage found"}
                      >
                        {s}
                        <span className="trace-hint">
                          {supported ? (active ? "hide source" : "show source") : "no source found"}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              {summary.action_items && summary.action_items.length > 0 && (
                <div className="ai-actions-list">
                  <b>Action items</b>
                  <ul>
                    {summary.action_items.map((a, i) => (
                      <li key={i}>
                        {a.text}
                        <span className="ai-src">from sentence {a.source_sentence}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {/* ------------------------------------------------------ draft (FR-03) */}
      {(draft || draftState === "loading" || draftError) && (
        <section className="ai-panel">
          <header className="ai-panel-head">
            <MessageSquareReply size={14} strokeWidth={2.4} /> <b>Draft reply</b>
            {draft && !draft.grounded && <span className="ai-chip warn">Unverified</span>}
            <button
              className="ai-close"
              onClick={() => { setDraft(null); setDraftState("idle"); setDraftError(null); setApproved(false); }}
              aria-label="Dismiss draft"
            >
              <X size={14} />
            </button>
          </header>

          {draftState === "loading" && <div className="ai-skel"><span /><span /><span /><span /></div>}
          {draftError && <p className="ai-error">{draftError}</p>}

          {draft && (
            <>
              <GroundingNotice grounded={draft.grounded} flags={draft.ungrounded_flags} />
              <textarea
                className="ai-draft"
                value={draftText}
                onChange={(e) => { setDraftText(e.target.value); setApproved(false); }}
                rows={10}
                aria-label="Draft reply, editable"
              />
              <div className="ai-draft-foot">
                <input
                  className="ai-instruction"
                  placeholder="Optional: how should it be written? e.g. accept the new time"
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                />
                <button
                  className="ai-approve"
                  onClick={() => setApproved(true)}
                  disabled={approved || !draftText.trim()}
                >
                  <Check size={15} strokeWidth={2.6} /> {approved ? "Approved" : "Approve"}
                </button>
              </div>
              {/* There is no send path in this build: not here, and no send
                  route on the server. Approval marks the text as reviewed and
                  stops there, which is what FR-03 asks for. */}
              <p className="ai-note">
                {approved
                  ? "Approved. Nothing has been sent — this build has no send capability."
                  : "Review and edit before approving. Nothing is sent automatically."}
              </p>
            </>
          )}
        </section>
      )}

      {/* --------------------------------------------------------- the email */}
      <div className="reader-head">
        <h2 className="reader-subject">{email.subject}</h2>
        <div className="reader-meta">
          <span className="mail-avatar lg" style={{ background: cat ? cat.color : "#64748B" }}>{initials}</span>
          <div className="reader-sender">
            <span className="reader-from">{email.sender_name || email.sender}</span>
            <span className="reader-addr">{email.sender}</span>
          </div>
          <div className="reader-right">
            <span className="cat-tag" style={{ "--c": cat ? cat.color : "#64748B" }}>
              <span className="cat-dot" /> {email.category}
            </span>
            <span className="reader-time">{email.received_at_display}</span>
          </div>
        </div>
      </div>

      <div className="reader-body">
        {bodyLoading && <div className="ai-skel"><span /><span /><span /><span /><span /></div>}
        {!bodyLoading && body && (() => {
          const entry = tracedSentence == null || !summary || !summary.provenance
            ? null
            : summary.provenance.find((pv) => pv.sentence === tracedSentence);
          const paragraphs = toParagraphs(segment(body, entry ? entry.spans : []));
          return paragraphs.map((pieces, i) =>
            pieces.length === 0 ? <br key={i} /> : (
              <p key={i}>
                {pieces.map((piece, j) =>
                  piece.highlighted
                    ? <mark className="trace-mark" key={j}>{piece.text}</mark>
                    : <span key={j}>{piece.text}</span>
                )}
              </p>
            )
          );
        })()}
        {!bodyLoading && !body && <p className="ai-error">Could not load this message.</p>}
      </div>
    </div>
  );
}
