/**
 * Settings (section 5.5): voice on/off, recognition language, translation
 * language, browser capability status, cache clear.
 *
 * Deliberately small. The FIT3163 wireframe also listed a default reply tone;
 * tone lives on the draft itself, where it applies. The wireframe's
 * translation language is here (FR-07): it is the language the reading pane's
 * Translate button starts in, and the translation itself has its own picker
 * for a quick switch.
 *
 * Every voice-triggered action has a click equivalent (SR-01), so turning
 * voice off removes nothing but the microphone and speaker controls.
 */

import { ChevronRight, Languages, Mic, RefreshCw, Volume2 } from "lucide-react";

import { useSpeech } from "../hooks/useSpeech.jsx";
import { capabilities } from "../lib/capabilities.js";
import { DEFAULT_TRANSLATION_LANGUAGE, LANGUAGES, SPEECH_LANGS } from "../lib/constants.js";

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

export default function Settings({
  voiceEnabled,
  setVoiceEnabled,
  speechLang,
  setSpeechLang,
  translationLang = DEFAULT_TRANSLATION_LANGUAGE,
  setTranslationLang,
  onReloadInbox,
  reloading,
  onBack,
}) {
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
          <p className="main-sub">Voice, translation, browser support, and cached data.</p>
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

        {/* Only where it can apply: with voice off, or no recogniser in this
            browser, a language choice would change nothing. */}
        {voiceEnabled && capabilities.stt && (
          <Row
            label="Recognition language"
            detail="The English your voice commands listen for. Pick the accent closest to yours: the browser's own language setting is often not the one you speak."
          >
            {/* A native select gives keyboard and screen reader support for
                free; .setting-select only matches it to the other controls. */}
            <select
              className="setting-select"
              aria-label="Recognition language"
              value={speechLang}
              onChange={(event) => setSpeechLang(event.target.value)}
            >
              {SPEECH_LANGS.map(({ key, label }) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </Row>
        )}
      </section>

      <section className="setting-group">
        <h2 className="setting-group-title">Translation</h2>

        {/* FR-07. Always offered: translation needs no browser capability. */}
        <Row
          label={<><Languages size={15} /> Translation language</>}
          detail="The language Translate uses first, for an email or a draft reply. Each translation can still be switched to another language on the spot."
        >
          <select
            className="setting-select"
            aria-label="Translation language"
            value={translationLang}
            onChange={(event) => setTranslationLang(event.target.value)}
          >
            {LANGUAGES.map(({ key }) => (
              <option key={key} value={key}>{key}</option>
            ))}
          </select>
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
