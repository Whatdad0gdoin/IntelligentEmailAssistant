/**
 * Summarise view (FR-01). Calls POST /api/summarise.
 *
 * What this deliberately does NOT do is render an empty state on failure. The
 * backend answers a summary it could not produce with an error status, never a
 * 200 carrying an empty summary, and this view keeps that contract intact: an
 * error is shown as an error. A blank panel would read as "the email said
 * nothing", which is a different and false claim.
 *
 * Response: { email_id, summary[], action_items[], grounded, ungrounded_flags[] }
 */

import { useEffect, useRef, useState } from "react";
import { ChevronRight, ListChecks, Sparkles, Square, Volume2 } from "lucide-react";

import EmailPicker from "../components/EmailPicker.jsx";
import GroundingNotice from "../components/GroundingNotice.jsx";
import useSpeech from "../hooks/useSpeech.js";
import * as api from "../api/client.js";

export default function Summarise({ emails, selected, setSelected, onBack }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const speech = useSpeech();
  const abortRef = useRef(null);

  const email = emails.find((e) => e.id === selected) || null;

  // Switching email invalidates the summary on screen. Leaving the previous
  // one visible under a new heading is the worst available outcome.
  useEffect(() => {
    setResult(null);
    setError(null);
  }, [selected]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = async () => {
    if (!email || loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.summarise(email.apiId, { signal: controller.signal }));
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const spoken = result ? result.summary.join(" ") : "";

  return (
    <div className="feature-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>Summarise</span>
      </div>

      <header className="feature-head">
        <div className="feature-icon"><Sparkles size={22} strokeWidth={2.2} /></div>
        <div>
          <h1 className="main-title">Summarise</h1>
          <p className="main-sub">Condense an email into a 2–3 sentence brief with action items.</p>
        </div>
      </header>

      <div className="feature-controls">
        <EmailPicker emails={emails} selected={selected} onSelect={setSelected} />
        <button className="primary-btn" onClick={run} disabled={!email || loading}>
          {loading ? <><span className="spinner sm" /> Summarising…</> : <><Sparkles size={15} strokeWidth={2.2} /> Summarise</>}
        </button>
      </div>

      {!email && <p className="feature-hint">Choose an email above to summarise it.</p>}

      {error && <div className="feature-error"><b>Could not summarise.</b><span>{error}</span></div>}

      {result && (
        <div className="feature-card summary-scroll">
          <div className="feature-card-head">
            <h2>{email.subject}</h2>
            {speech.supported && (
              <button
                className="action-btn"
                onClick={() => (speech.speaking ? speech.stop() : speech.speak(spoken))}
              >
                {speech.speaking
                  ? <><Square size={14} strokeWidth={2.4} /> Stop</>
                  : <><Volume2 size={15} strokeWidth={2.2} /> Read aloud</>}
              </button>
            )}
          </div>

          {result.summary.map((sentence, i) => (
            <p className="summary-line" key={i}>{sentence}</p>
          ))}

          {result.action_items.length > 0 && (
            <div className="action-items">
              <h3><ListChecks size={15} strokeWidth={2.2} /> Action items</h3>
              <ul>
                {result.action_items.map((item, i) => (
                  <li key={i}>
                    {item.text}
                    {/* Traceability: every item points back at the sentence it
                        came from, which is the field's whole reason to exist. */}
                    <span className="item-src">from sentence {item.source_sentence}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <GroundingNotice grounded={result.grounded} flags={result.ungrounded_flags} />
        </div>
      )}
    </div>
  );
}
