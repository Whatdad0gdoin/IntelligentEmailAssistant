/**
 * Authenticated app shell.
 *
 * Two destinations: Inbox and Settings. The AI actions are not destinations;
 * Summarise, Read Aloud, Draft Reply and Translate act on the open message
 * inside the reading pane, and tone lives on the draft. The translation
 * language chosen in Settings is passed down as the language Translate starts
 * in.
 *
 * Under Inbox the sidebar lists what narrows it: the five categories with
 * their counts, and two quick filters (unread, with attachments). They are one
 * choice, held here as `filter`; Inbox itself is "all". At its foot the
 * sidebar says what state voice is in, and that card opens Settings.
 *
 * A command bar sits above both destinations, in every browser and whatever
 * the voice setting. A command can be typed into it anywhere, and spoken into
 * it where the browser can recognise speech: the bar carries the microphone,
 * and there is no separate voice page. Typed or spoken, the text goes to the
 * same intent route and is dispatched through the same runVoiceAction.
 *
 * Voice can be switched off in Settings. That hides the microphone and speaker
 * controls and nothing else: every voice action already has a click equivalent
 * (SR-01), so the app loses no capability, only its voice buttons.
 */

import { useEffect, useMemo, useState } from "react";
import { LogOut, Mail, Mic, MicOff, Paperclip, Settings as SettingsIcon } from "lucide-react";

import CommandBar from "./CommandBar.jsx";
import SideItem from "./SideItem.jsx";
import InboxView from "../views/Inbox.jsx";
import SettingsView from "../views/Settings.jsx";
import { useInbox } from "../hooks/useInbox.jsx";
import { usePreference } from "../hooks/usePreference.jsx";
import {
  CATEGORIES,
  DEFAULT_SPEECH_LANG,
  DEFAULT_TRANSLATION_LANGUAGE,
  FEATURES,
  REVIEW_CATEGORY,
  SPEECH_LANGS,
  speechLangOrDefault,
  translationLangOrDefault,
} from "../lib/constants.js";
import { capabilities, voiceLimitation } from "../lib/capabilities.js";
import { QUICK_FILTERS, newestFirst } from "../lib/search.js";
import { voiceStatus } from "../lib/voiceStatus.js";

const INBOX_FEATURE = FEATURES.find((f) => f.id === "inbox");

// The five buckets the inbox is grouped into, in the order it lists them.
const SIDE_CATEGORIES = [...CATEGORIES, REVIEW_CATEGORY];

const QUICK_FILTER_ICONS = { unread: Mail, attachments: Paperclip };

export default function Dashboard({ user, onLogout }) {
  const [active, setActive] = useState("inbox");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);
  const [voiceEnabled, setVoiceEnabled] = usePreference("voiceEnabled", true);
  const [storedSpeechLang, setSpeechLang] = usePreference("speechLang", DEFAULT_SPEECH_LANG);
  const speechLang = speechLangOrDefault(storedSpeechLang);
  // Stored as mailkit:translationLang. Read through the same guard as the
  // recognition language, so a stale value cannot become a refused request.
  const [storedTranslationLang, setTranslationLang] =
    usePreference("translationLang", DEFAULT_TRANSLATION_LANGUAGE);
  const translationLang = translationLangOrDefault(storedTranslationLang);

  const inbox = useInbox(true);
  const { loadBody } = inbox;

  // Only worth showing while voice is on: if the user turned it off, telling
  // them their browser cannot do it anyway is noise.
  const voiceNotice = voiceEnabled ? voiceLimitation() : null;

  // Opening an email pulls its body on demand; the list only carries snippets.
  // Keyed on the stable loadBody, not the inbox object, so this runs when the
  // selection changes and not on every render.
  useEffect(() => {
    if (selected) loadBody(selected);
  }, [selected, loadBody]);

  // A spoken command needs speech recognition. Without it, or with voice
  // turned off, the command bar shows no microphone rather than a dead one.
  const voiceAvailable = voiceEnabled && capabilities.stt;

  const allEmails = Object.values(inbox.groups).flat();
  // The candidates for a command, spoken or typed: one list, built once.
  //
  // Newest first, because the backend reads the first candidate as "the latest
  // email" and keeps only the first 100. The inbox arrives grouped by category,
  // and flattening the groups put the newest *Work* email first: "summarise the
  // latest email" summarised that, and a long inbox lost whole later categories
  // to the cap. newestFirst keeps ties in inbox order and puts an email with no
  // usable date last rather than guessing it into place. received_at goes too,
  // so the backend can check the order itself rather than trust it (it re-sorts
  // whenever the dates are supplied).
  const voiceEmails = useMemo(
    () =>
      Object.values(inbox.groups)
        .flat()
        .sort(newestFirst)
        .map((e) => ({
          apiId: e.id,
          from: e.sender_name || e.sender,
          subject: e.subject,
          receivedAt: e.received_at,
        })),
    [inbox.groups]
  );

  // A recognised intent, spoken or typed, selects its target and hands the
  // action to the reader. Returns false when the target cannot be determined:
  // section 6.3 says ask, never guess, so nothing falls back to "the first
  // email".
  const runVoiceAction = (intent, targetEmailId) => {
    const target = targetEmailId || selected;
    if (!target) return false;
    setSelected(target);
    setActive("inbox");
    setPendingAction({ intent, emailId: target });
    return true;
  };

  const openEmail = selected ? inbox.findEmail(selected) : null;
  const unreadCount = allEmails.filter(QUICK_FILTERS.unread.test).length;

  // The sidebar's categories and quick filters are one choice. Picking one
  // from Settings also brings the inbox back, as picking Inbox does.
  const showFilter = (name) => {
    setFilter(name);
    setActive("inbox");
  };
  const showing = (name) => active === "inbox" && filter === name;

  const voice = voiceStatus(
    voiceEnabled,
    SPEECH_LANGS.find((lang) => lang.key === speechLang)?.label,
    capabilities
  );

  let main;
  if (active === "settings") {
    main = (
      <SettingsView
        voiceEnabled={voiceEnabled}
        setVoiceEnabled={setVoiceEnabled}
        speechLang={speechLang}
        setSpeechLang={setSpeechLang}
        translationLang={translationLang}
        setTranslationLang={setTranslationLang}
        onReloadInbox={inbox.reload}
        reloading={inbox.loading}
        onMailboxChanged={inbox.reload}
        onBack={() => setActive("inbox")}
      />
    );
  } else {
    main = (
      <InboxView
        groups={inbox.groups}
        loading={inbox.loading}
        error={inbox.error}
        filter={filter}
        setFilter={setFilter}
        selected={selected}
        setSelected={setSelected}
        openEmail={openEmail}
        openBody={selected ? inbox.bodies[selected] : undefined}
        bodyLoading={inbox.bodyLoading && selected != null && inbox.bodies[selected] === undefined}
        onRetry={inbox.reload}
        pendingAction={pendingAction}
        onActionConsumed={() => setPendingAction(null)}
        voiceEnabled={voiceEnabled}
        translationLang={translationLang}
        speechLang={speechLang}
      />
    );
  }

  return (
    <div className="dash-root">
      <aside className="sidebar">
        <div className="side-brand">
          <div className="brand-glyph sm"><span className="glyph-mk sm">MK</span></div>
          <span className="brand-name sm">Mail<b>Kit</b></span>
        </div>
        <nav className="side-nav" aria-label="Mailbox">
          <SideItem
            f={INBOX_FEATURE}
            active={showing("all") ? INBOX_FEATURE.id : null}
            onClick={() => showFilter("all")}
            badge={unreadCount}
          />

          {/* Counts wait for the load: while the inbox is being classified
              every one of them would read 0. The title names the item when
              the sidebar is collapsed to icons on a narrow window. */}
          <div className="nav-group-label">Categories</div>
          {SIDE_CATEGORIES.map(({ label, tint }) => (
            <button
              className={`nav-item ${showing(label) ? "active" : ""}`}
              key={label}
              title={label}
              aria-current={showing(label) ? "true" : undefined}
              onClick={() => showFilter(label)}
            >
              <span className="nav-icon"><span className="nav-dot" style={{ background: tint }} /></span>
              <span className="nav-label">{label}</span>
              {!inbox.loading && <span className="nav-count">{(inbox.groups[label] || []).length}</span>}
            </button>
          ))}

          <div className="nav-group-label">Filters</div>
          {Object.entries(QUICK_FILTERS).map(([key, { label, test }]) => {
            const Icon = QUICK_FILTER_ICONS[key];
            return (
              <button
                className={`nav-item ${showing(key) ? "active" : ""}`}
                key={key}
                title={label}
                aria-current={showing(key) ? "true" : undefined}
                onClick={() => showFilter(key)}
              >
                <span className="nav-icon"><Icon size={16} strokeWidth={2.2} /></span>
                <span className="nav-label">{label}</span>
                {!inbox.loading && <span className="nav-count">{allEmails.filter(test).length}</span>}
              </button>
            );
          })}
        </nav>
        <div className="side-foot">
          {/* Says what voice is doing by its words and its icon, not only the
              dot. It opens Settings, where voice is switched and explained. */}
          <button className="side-voice" title="Change this in Settings" onClick={() => setActive("settings")}>
            <span className={`side-voice-icon ${voice.live ? "live" : ""}`}>
              {voice.live
                ? <Mic size={16} strokeWidth={2.2} aria-hidden="true" />
                : <MicOff size={16} strokeWidth={2.2} aria-hidden="true" />}
            </span>
            <span className="side-voice-text">
              <span className="side-voice-title">{voice.title}</span>
              <span className="side-voice-detail">{voice.detail}</span>
            </span>
            <span className={`side-voice-dot ${voice.live ? "live" : ""}`} />
          </button>
          <button className={`side-mini ${active === "settings" ? "active" : ""}`} onClick={() => setActive("settings")}>
            <SettingsIcon size={17} /> <span>Settings</span>
          </button>
          <div className="side-user">
            <div className="user-avatar">{user.email[0]?.toUpperCase()}</div>
            <div className="user-meta">
              <span className="user-email">{user.email}</span>
              <span className="user-plan">Signed in</span>
            </div>
            <button className="logout-btn" onClick={onLogout} aria-label="Log out"><LogOut size={16} /></button>
          </div>
        </div>
      </aside>

      {/* The inbox fills the height left under the notice and the command bar
          (dash-fill), so neither pushes the bottom of the list and the reader
          off screen. The other views are pages that scroll as before. */}
      <main className={active === "inbox" ? "dash-main dash-fill" : "dash-main"}>
        {/* SR-01: persistent, non-blocking, and never gates a feature. */}
        {voiceNotice && <div className="voice-notice" role="status">{voiceNotice}</div>}
        {/* The bar itself is outside the voice switch and the capability check
            on purpose: typing needs neither a microphone nor a recogniser, so
            it is the command path every browser keeps. Only its microphone
            depends on them. */}
        <CommandBar
          emails={voiceEmails}
          onRun={runVoiceAction}
          voice={voiceAvailable}
          readAloud={voiceEnabled && capabilities.tts}
          speechLang={speechLang}
        />
        <div className="dash-view">{main}</div>
      </main>
    </div>
  );
}
