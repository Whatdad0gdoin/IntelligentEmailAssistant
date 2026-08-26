/**
 * Authenticated app shell.
 *
 * The AI features are no longer separate destinations: Summarise, Read Aloud
 * and Draft Reply all act on the open email inside the reading pane. The
 * sidebar entries for them now select the inbox and say so, rather than
 * navigating to a screen that repeats what the reader already offers.
 *
 * Tone and Translate stay as honest "not built" placeholders -- they are
 * FR-06/FR-07 and out of scope for this build.
 */

import { useEffect, useState } from "react";
import { LogOut, PenLine, Settings as SettingsIcon } from "lucide-react";

import ComingSoon from "./ComingSoon.jsx";
import SideItem from "./SideItem.jsx";
import InboxView from "../views/Inbox.jsx";
import SettingsView from "../views/Settings.jsx";
import VoiceView from "../views/Voice.jsx";
import { useInbox } from "../hooks/useInbox.jsx";
import { FEATURES } from "../lib/constants.js";
import { voiceLimitation } from "../lib/capabilities.js";

// Voice Commands is the only AI feature with a screen of its own: FR-05 acts
// on the inbox as a whole rather than on one message, and it dispatches its
// recognised intent into the reading pane. Everything else lives on the email.
const VOICE_FEATURE = FEATURES.find((f) => f.id === "voice");

export default function Dashboard({ user, onLogout }) {
  const [active, setActive] = useState("inbox");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);

  const inbox = useInbox(true);
  const voiceNotice = voiceLimitation();


  // Opening an email pulls its body on demand; the list only carries snippets.
  useEffect(() => {
    if (selected) inbox.loadBody(selected);
  }, [selected, inbox]);

  const handleNav = (id) => setActive(id);

  const allEmails = Object.values(inbox.groups).flat();
  const voiceEmails = allEmails.map((e) => ({
    apiId: e.id,
    from: e.sender_name || e.sender,
    subject: e.subject,
  }));

  // A recognised intent selects its target and hands the action to the reader.
  // Returns true when the action was dispatched, false when the target could
  // not be determined. Section 6.3 is explicit: on an unresolved reference the
  // app asks rather than guesses. Falling back to the first email in the inbox
  // is exactly the "confidently wrong action" the spec warns about - it is how
  // "summarise the email from Sarah" ends up summarising someone else's mail.
  const runVoiceAction = (intent, targetEmailId) => {
    const target = targetEmailId || selected;
    if (!target) return false;
    setSelected(target);
    setActive("inbox");
    setPendingAction({ intent, emailId: target });
    return true;
  };

  const openEmail = selected ? inbox.findEmail(selected) : null;
  const unreadCount = Object.values(inbox.groups).reduce(
    (n, list) => n + list.filter((e) => e.unread).length,
    0
  );

  let main;
  if (active === "inbox") {
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
      />
    );
  } else if (active === "voice") {
    main = <VoiceView emails={voiceEmails} onRun={runVoiceAction} onBack={() => setActive("inbox")} />;
  } else if (active === "settings") {
    main = <SettingsView onBack={() => setActive("inbox")} />;
  } else {
    main = <ComingSoon feature={FEATURES.find((f) => f.id === active)} onBack={() => setActive("inbox")} />;
  }

  return (
    <div className="dash-root">
      <aside className="sidebar">
        <div className="side-brand">
          <div className="brand-glyph sm"><span className="glyph-mk sm">MK</span></div>
          <span className="brand-name sm">Mail<b>Kit</b></span>
        </div>
        <button className="compose-btn"><PenLine size={16} strokeWidth={2.4} /> <span>Compose</span></button>
        <nav className="side-nav">
          {/* The AI Tools group is gone. Summarise, Read Aloud and Draft Reply
              act on an open message, so they belong on that message, not in a
              global nav that could only ever say "open an email first".
              What remains is genuinely navigable: places, not verbs. */}
          <SideItem f={FEATURES[0]} active={active} onClick={handleNav} badge={unreadCount} />
          {VOICE_FEATURE && (
            <>
              <div className="nav-group-label">Hands-free</div>
              <SideItem f={VOICE_FEATURE} active={active} onClick={handleNav} />
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
