/**
 * Settings (section 5.5): voice on/off, browser capability status, cache clear.
 *
 * Deliberately small. The FIT3163 wireframe also listed default reply tone and
 * translation language; tone now lives on the draft itself where it applies,
 * and translation (FR-07) is out of scope for this build.
 *
 * Every voice-triggered action has a click equivalent (SR-01), so turning
 * voice off removes nothing but the microphone and speaker controls.
 */

import { ChevronRight, Mic, RefreshCw, Volume2 } from "lucide-react";

import { useSpeech } from "../hooks/useSpeech.jsx";
import { capabilities } from "../lib/capabilities.js";

function Row({ label, detail, children }) {
  return (
    <div className="setting-row">
      <div className="setting-text">
        <span className="setting-label">{label}</span>
        {detail && <span className="setting-detail">{detail}</span>}
      </div>
      <div className="setting-control">{children}</div>
    </div>
  );
}

function Status({ ok, children }) {
  return (
    <span className={`setting-status ${ok ? "ok" : "off"}`}>
      <span className="setting-dot" />
      {children}
    </span>
  );
}

export default function Settings({ voiceEnabled, setVoiceEnabled, onReloadInbox, reloading, onBack }) {
  const speech = useSpeech();

  return (
    <div className="feature-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>Settings</span>
      </div>

      <header className="feature-head">
        <div>
          <h1 className="main-title">Settings</h1>
          <p className="main-sub">Voice, browser support, and cached data.</p>
        </div>
      </header>

      <section className="setting-group">
        <h2 className="setting-group-title">Voice</h2>

        <Row
          label="Voice features"
          detail="Read Aloud and Voice Commands. Everything they do is also a button."
        >
          <button
            className={`toggle ${voiceEnabled ? "on" : ""}`}
            role="switch"
            aria-checked={voiceEnabled}
            onClick={() => setVoiceEnabled((v) => !v)}
          >
            <span className="toggle-knob" />
            <span className="toggle-text">{voiceEnabled ? "On" : "Off"}</span>
          </button>
        </Row>
      </section>

      <section className="setting-group">
        <h2 className="setting-group-title">This browser</h2>

        <Row label={<><Volume2 size={15} /> Text to speech</>}
             detail={capabilities.tts
               ? (speech.voiceName ? `Using "${speech.voiceName}"` : "Available")
               : "Not available in this browser"}>
          <Status ok={capabilities.tts}>{capabilities.tts ? "Supported" : "Unsupported"}</Status>
        </Row>

        {capabilities.tts && (
          <Row label="Voice quality"
               detail={speech.isNeural
                 ? "A neural voice is in use, which is the most natural option this browser offers."
                 : "Only a local system voice is available. Edge on Windows 11 and Chrome offer neural voices that sound far less robotic."}>
            <Status ok={speech.isNeural}>{speech.isNeural ? "Neural" : "Basic"}</Status>
          </Row>
        )}

        <Row label={<><Mic size={15} /> Speech recognition</>}
             detail={capabilities.stt ? "Available" : "Chrome and Edge support this today; Firefox and Safari do not"}>
          <Status ok={capabilities.stt}>{capabilities.stt ? "Supported" : "Unsupported"}</Status>
        </Row>
      </section>

      <section className="setting-group">
        <h2 className="setting-group-title">Data</h2>

        <Row
          label="Reload inbox"
          detail="Fetches your mail again and re-runs categorisation. Open message text held in this tab is discarded."
        >
          <button className="action-btn" onClick={onReloadInbox} disabled={reloading}>
            <RefreshCw size={15} strokeWidth={2.2} className={reloading ? "spin" : ""} />
            <span>{reloading ? "Reloading" : "Reload"}</span>
          </button>
        </Row>

        <p className="setting-footnote">
          Nothing from your emails is stored by this browser. Message text is fetched when you
          open a message and kept only for this tab; the sign-in token is kept in memory and is
          cleared on refresh.
        </p>
      </section>
    </div>
  );
}
