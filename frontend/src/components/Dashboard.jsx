/**
 * Authenticated app shell.
 *
 * Routing note. This used to send every AI and Voice feature to <ComingSoon>
 * and pass a hardcoded `soon` prop to every one of their sidebar entries. That
 * was accurate when none of the routes existed; it stopped being accurate the
 * moment they shipped, and nothing in the code noticed, because the badge and
 * the placeholder were both literals rather than statements about the build.
 *
 * Now there is one source of truth: `soon` lives on the feature in
 * lib/constants.js, the sidebar reads it, and this switch sends a feature to
 * <ComingSoon> only when the feature actually carries the flag. Tone &
 * Translate (FR-06/FR-07) and Settings are the two that still do -- there is no
 * endpoint behind either of them.
 */

import { useEffect, useRef, useState } from "react";
import { Hammer, LogOut, PenLine, Settings as SettingsIcon } from "lucide-react";

import ComingSoon from "./ComingSoon.jsx";
import SideItem from "./SideItem.jsx";
import CategoriseView from "../views/Categorise.jsx";
import DraftView from "../views/Draft.jsx";
import InboxView from "../views/Inbox.jsx";
import SettingsView from "../views/Settings.jsx";
import SpeakView from "../views/Speak.jsx";
import SummariseView from "../views/Summarise.jsx";
import VoiceView from "../views/Voice.jsx";
import { FEATURES } from "../lib/constants.js";

/** Voice intent -> the view that performs it (FR-05). */
const INTENT_VIEW = { summarise: "summarise", read: "speak", draft: "reply" };

export default function Dashboard({ user, emails, onLogout }) {
  const [active, setActive] = useState("inbox");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const showToast = (label) => {
    setToast(label);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  };

  const activeFeature = FEATURES.find((f) => f.id === active);
  const shown = filter === "all" ? emails : emails.filter((e) => e.cat === filter);
  const unreadCount = emails.filter((e) => e.unread).length;

  const backToInbox = () => setActive("inbox");

  /** A confirmed voice intent lands the user on the view that does the thing. */
  const runIntent = (intent, emailId) => {
    if (emailId) setSelected(emailId);
    setActive(INTENT_VIEW[intent] ?? "inbox");
  };

  const featureProps = { emails, selected, setSelected, onBack: backToInbox };

  let main;
  if (active === "inbox") {
    main = (
      <InboxView
        emails={emails}
        shown={shown}
        filter={filter}
        setFilter={setFilter}
        selected={selected}
        setSelected={setSelected}
        unreadCount={unreadCount}
        onFeature={setActive}
        onUnavailable={showToast}
      />
    );
  } else if (active === "summarise") {
    main = <SummariseView {...featureProps} />;
  } else if (active === "categorise") {
    main = <CategoriseView emails={emails} onBack={backToInbox} />;
  } else if (active === "reply") {
    main = <DraftView {...featureProps} />;
  } else if (active === "speak") {
    main = <SpeakView {...featureProps} />;
  } else if (active === "voice") {
    main = <VoiceView emails={emails} onRun={runIntent} onBack={backToInbox} />;
  } else if (active === "settings") {
    main = <SettingsView onBack={backToInbox} />;
  } else {
    main = <ComingSoon feature={activeFeature} onBack={backToInbox} />;
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
          <SideItem f={FEATURES[0]} active={active} onClick={setActive} badge={unreadCount} />
          <div className="nav-group-label">AI Tools</div>
          {FEATURES.filter((f) => f.group === "ai").map((f) => <SideItem key={f.id} f={f} active={active} onClick={setActive} />)}
          <div className="nav-group-label">Voice</div>
          {FEATURES.filter((f) => f.group === "voice").map((f) => <SideItem key={f.id} f={f} active={active} onClick={setActive} />)}
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

      <main className="dash-main">{main}</main>

      {toast && (
        <div className="toast" key={toast}>
          <span className="toast-icon"><Hammer size={15} strokeWidth={2.4} /></span>
          <div className="toast-text">
            <b>{toast}</b>
            <span>Not built in this release — FR-06/FR-07 are out of scope.</span>
          </div>
        </div>
      )}
    </div>
  );
}
