/**
 * Draft Reply view (FR-03). Calls POST /api/draft.
 *
 * The draft lands in an editable textarea and stays there. There is no Send
 * button, because there is no send endpoint -- the backend has none by design
 * and tests/test_draft.py asserts the URL map still has none. Generating a
 * reply and sending a reply are two decisions, and only the first one is the
 * model's. Copy-to-clipboard is as far as this view goes.
 *
 * Response: { draft, grounded, ungrounded_flags[] }
 */

import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Copy, MessageSquareReply, RefreshCw } from "lucide-react";

import EmailPicker from "../components/EmailPicker.jsx";
import GroundingNotice from "../components/GroundingNotice.jsx";
import * as api from "../api/client.js";

export default function Draft({ emails, selected, setSelected, onBack }) {
  const [instruction, setInstruction] = useState("");
  const [result, setResult] = useState(null);
  const [text, setText] = useState("");        // the user's edits, not the model's output
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef(null);
  const copyTimer = useRef(null);

  const email = emails.find((e) => e.id === selected) || null;

  useEffect(() => {
    setResult(null);
    setText("");
    setError(null);
  }, [selected]);

  useEffect(() => () => {
    abortRef.current?.abort();
    clearTimeout(copyTimer.current);
  }, []);

  const run = async () => {
    if (!email || loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const payload = await api.draft(email.apiId, instruction, { signal: controller.signal });
      setResult(payload);
      setText(payload.draft);
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Could not copy to the clipboard.");
    }
  };

  // The grounding flags describe the text the model returned. Once the user
  // edits it they describe something that is no longer on screen, so they are
  // withdrawn rather than left to vouch for text nobody checked.
  const edited = result !== null && text !== result.draft;

  return (
    <div className="feature-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>Draft Reply</span>
      </div>

      <header className="feature-head">
        <div className="feature-icon"><MessageSquareReply size={22} strokeWidth={2.2} /></div>
        <div>
          <h1 className="main-title">Draft Reply</h1>
          <p className="main-sub">Generate a reply, then review and edit it yourself. Nothing is sent.</p>
        </div>
      </header>

      <div className="feature-controls">
        <EmailPicker emails={emails} selected={selected} onSelect={setSelected} label="Replying to" />
      </div>

      <label className="field instruction-field">
        <span className="field-label">Instruction (optional)</span>
        <div className="field-wrap">
          <input
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="e.g. accept the new time, but ask for the agenda first"
          />
        </div>
      </label>

      <button className="primary-btn" onClick={run} disabled={!email || loading}>
        {loading
          ? <><span className="spinner sm" /> Drafting…</>
          : result
            ? <><RefreshCw size={15} strokeWidth={2.2} /> Regenerate</>
            : <><MessageSquareReply size={15} strokeWidth={2.2} /> Draft reply</>}
      </button>

      {!email && <p className="feature-hint">Choose an email above to draft a reply to it.</p>}

      {error && <div className="feature-error"><b>Could not draft a reply.</b><span>{error}</span></div>}

      {result && (
        <div className="feature-card">
          <textarea
            className="draft-area"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={12}
            aria-label="Draft reply"
          />

          <div className="draft-foot">
            <button className="action-btn" onClick={copy}>
              {copied ? <><Check size={15} strokeWidth={2.4} /> Copied</> : <><Copy size={15} strokeWidth={2.2} /> Copy</>}
            </button>
            <span className="draft-note">
              This app cannot send email. Paste the reply into your mail client when you're happy with it.
            </span>
          </div>

          {edited ? (
            <div className="ground-note edit">
              You've edited this draft, so the checks below no longer describe what's on screen.
            </div>
          ) : (
            <GroundingNotice grounded={result.grounded} flags={result.ungrounded_flags} />
          )}
        </div>
      )}
    </div>
  );
}
