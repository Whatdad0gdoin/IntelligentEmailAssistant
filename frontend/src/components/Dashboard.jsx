/**
 * Authenticated app shell.
 *
 * Three destinations: Inbox, Voice Commands, Settings. The AI actions are not
 * destinations; Summarise, Read Aloud and Draft Reply act on the open message
 * inside the reading pane, and tone lives on the draft.
 *
 * Voice can be switched off in Settings. That hides the microphone and speaker
 * controls and nothing else: every voice action already has a click equivalent
 * (SR-01), so the app loses no capability, only two buttons.
 */

import { useEffect, useState } from "react";
import { LogOut, Settings as SettingsIcon } from "lucide-react";

import SideItem from "./SideItem.jsx";
import InboxView from "../views/Inbox.jsx";
import SettingsView from "../views/Settings.jsx";
import VoiceView from "../views/Voice.jsx";
import { useInbox } from "../hooks/useInbox.jsx";
import { usePreference } from "../hooks/usePreference.jsx";
import { FEATURES } from "../lib/constants.js";
import { capabilities, voiceLimitation } from "../lib/capabilities.js";

const INBOX_FEATURE = FEATURES.find((f) => f.id === "inbox");
const VOICE_FEATURE = FEATURES.find((f) => f.id === "voice");

export default function Dashboard({ user, onLogout }) {
  const [active, setActive] = useState("inbox");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);
  const [voiceEnabled, setVoiceEnabled] = usePreference("voiceEnabled", true);

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

  // Voice Commands needs speech recognition. Without it, or with voice turned
  // off, the destination is removed rather than shown as a dead end.
  const voiceAvailable = voiceEnabled && capabilities.stt;
  useEffect(() => {
    if (active === "voice" && !voiceAvailable) setActive("inbox");
  }, [active, voiceAvailable]);

  const allEmails = Object.values(inbox.groups).flat();
  const voiceEmails = allEmails.map((e) => ({
    apiId: e.id,
    from: e.sender_name || e.sender,
    subject: e.subject,
  }));

  // A recognised intent selects its target and hands the action to the reader.
  // Returns false when the target cannot be determined: section 6.3 says ask,
  // never guess, so nothing falls back to "the first email".
  const runVoiceAction = (intent, targetEmailId) => {
    const target = targetEmailId || selected;
    if (!target) return false;
    setSelected(target);
    setActive("inbox");
    setPendingAction({ intent, emailId: target });
    return true;
  };

  const openEmail = selected ? inbox.findEmail(selected) : null;
  const unreadCount = allEmails.filter((e) => e.unread).length;

  let main;
  if (active === "voice") {
    main = <VoiceView emails={voiceEmails} onRun={runVoiceAction} onBack={() => setActive("inbox")} />;
  } else if (active === "settings") {
    main = (
      <SettingsView
        voiceEnabled={voiceEnabled}
        setVoiceEnabled={setVoiceEnabled}
        onReloadInbox={inbox.reload}
        reloading={inbox.loading}
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
        <nav className="side-nav">
          <SideItem f={INBOX_FEATURE} active={active} onClick={setActive} badge={unreadCount} />
          {voiceAvailable && (
            <>
              <div className="nav-group-label">Hands-free</div>
              <SideItem f={VOICE_FEATURE} active={active} onClick={setActive} />
            </>
          )}
        </nav>
        <div className="side-foot">
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

      <main className="dash-main">
        {/* SR-01: persistent, non-blocking, and never gates a feature. */}
        {voiceNotice && <div className="voice-notice" role="status">{voiceNotice}</div>}
        {main}
      </main>
    </div>
  );
}
