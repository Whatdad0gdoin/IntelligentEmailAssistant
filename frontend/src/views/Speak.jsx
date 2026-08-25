/**
 * Read Aloud view. Browser speech synthesis, no backend call.
 *
 * Offers the email itself or an AI summary of it. The summary route goes
 * through POST /api/summarise like everything else rather than re-deriving one
 * here, so what you hear is the same text FR-01 would show you.
 */

import { useEffect, useRef, useState } from "react";
import { ChevronRight, Sparkles, Square, Volume2 } from "lucide-react";

import EmailPicker from "../components/EmailPicker.jsx";
import useSpeech from "../hooks/useSpeech.js";
import * as api from "../api/client.js";

export default function Speak({ emails, selected, setSelected, onBack }) {
  const speech = useSpeech();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const email = emails.find((e) => e.id === selected) || null;

  useEffect(() => {
    speech.stop();
    setError(null);
  }, [selected]);           // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => abortRef.current?.abort(), []);

  const speakSummary = async () => {
    if (!email || loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const payload = await api.summarise(email.apiId, { signal: controller.signal });
      speech.speak(payload.summary.join(" "));
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  return (
    <div className="feature-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>Read Aloud</span>
      </div>

      <header className="feature-head">
        <div className="feature-icon"><Volume2 size={22} strokeWidth={2.2} /></div>
        <div>
          <h1 className="main-title">Read Aloud</h1>
          <p className="main-sub">Listen to an email, or to a summary of it. Playback happens on your device.</p>
        </div>
      </header>

      {!speech.supported ? (
        <div className="feature-error">
          <b>This browser has no speech synthesis.</b>
          <span>Read Aloud needs the Web Speech API, and your browser doesn't expose it.</span>
        </div>
      ) : (
        <>
          <div className="feature-controls">
            <EmailPicker emails={emails} selected={selected} onSelect={setSelected} />
          </div>

          <div className="reader-actions">
            <button
              className="primary-btn"
              onClick={() => speech.speak(`${email.subject}. From ${email.from}. ${email.body}`)}
              disabled={!email || speech.speaking}
            >
              <Volume2 size={15} strokeWidth={2.2} /> Read the email
            </button>
            <button className="action-btn" onClick={speakSummary} disabled={!email || loading}>
              {loading ? <><span className="spinner sm dark" /> Summarising…</> : <><Sparkles size={15} strokeWidth={2.2} /> Read a summary</>}
            </button>
            {speech.speaking && (
              <button className="action-btn" onClick={speech.stop}>
                <Square size={14} strokeWidth={2.4} /> Stop
              </button>
            )}
          </div>

          {!email && <p className="feature-hint">Choose an email above to hear it.</p>}
          {error && <div className="feature-error"><b>Could not summarise.</b><span>{error}</span></div>}
        </>
      )}
    </div>
  );
}
