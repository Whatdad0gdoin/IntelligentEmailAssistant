/**
 * Authenticated app shell. Adapted from the teammate's Dashboard.
 *
 * Changes from the original:
 *  - emails come from a prop rather than a module-scope constant, so step 4 can
 *    swap the placeholder fixtures for GET /api/inbox without touching layout;
 *  - the Settings button is wired (it was a dead control with no onClick);
 *  - the toast timer no longer hangs off `window`.
 */

import { useEffect, useRef, useState } from "react";
import { Hammer, Inbox as InboxIcon, LogOut, PenLine, Settings as SettingsIcon } from "lucide-react";

import ComingSoon from "./ComingSoon.jsx";
import SideItem from "./SideItem.jsx";
import DraftView from "../views/Draft.jsx";
import InboxView from "../views/Inbox.jsx";
import SettingsView from "../views/Settings.jsx";
import { FEATURES } from "../lib/constants.js";

export default function Dashboard({ user, emails, onLogout }) {
  const [active, setActive] = useState("inbox");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  // The original stashed this timer on window.__iqToast, which leaks across
  // mounts and survives logout. A ref is scoped to the component and cleans up.
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
        onAction={showToast}
      />
    );
  } else if (active === "settings") {
    main = <SettingsView onBack={backToInbox} />;
  } else if (active === "reply") {
    main = <DraftView onBack={backToInbox} />;
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
          {FEATURES.filter((f) => f.group === "ai").map((f) => <SideItem key={f.id} f={f} active={active} onClick={setActive} soon />)}
          <div className="nav-group-label">Voice</div>
          {FEATURES.filter((f) => f.group === "voice").map((f) => <SideItem key={f.id} f={f} active={active} onClick={setActive} soon />)}
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
            <span>This feature is not functional yet - coming in a later step.</span>
          </div>
        </div>
      )}
    </div>
  );
}
