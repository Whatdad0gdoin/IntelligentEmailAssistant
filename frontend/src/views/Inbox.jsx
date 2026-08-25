/**
 * Inbox view (FR-08).
 *
 * Adapted from the original InboxView. Markup and CSS classes are unchanged;
 * the one structural change is that the email list now arrives as a prop
 * instead of being read from a module-scope constant. The original component
 * took `shown` as a prop but still reached for the module-level EMAILS array
 * for its counts, which meant the list and the counts had two different
 * sources -- that has to be one source before a real API can feed it (step 4).
 *
 * NOT YET DONE (step 4): grouping by category, the Review bucket, and the
 * skeleton loader. Today this still renders one flat list, as the teammate
 * wrote it.
 */

import { Bell, Inbox as InboxIcon, Paperclip, Search, Star } from "lucide-react";

import ReadingPane from "../components/ReadingPane.jsx";
import { CATEGORIES } from "../lib/constants.js";

export default function Inbox({
  emails,
  shown,
  filter,
  setFilter,
  selected,
  setSelected,
  unreadCount,
  onFeature,
  onUnavailable,
}) {
  const openEmail = shown.find((e) => e.id === selected) || emails.find((e) => e.id === selected);

  return (
    <div className={`inbox-split ${selected ? "has-selection" : ""}`}>
      {/* LEFT: list */}
      <div className="inbox-left">
        <header className="main-head">
          <div>
            <h1 className="main-title">Inbox</h1>
            <p className="main-sub">{unreadCount} unread · {emails.length} total</p>
          </div>
          <div className="head-actions">
            <button className="icon-btn" aria-label="Notifications"><Bell size={18} /></button>
          </div>
        </header>

        <div className="search-box wide">
          <Search size={16} className="search-icon" />
          <input placeholder="Search mail…" />
        </div>

        <div className="filter-row">
          <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
            All <span className="chip-count">{emails.length}</span>
          </button>
          {CATEGORIES.map((c) => {
            const n = emails.filter((e) => e.cat === c.key).length;
            return (
              <button key={c.key} className={`chip ${filter === c.key ? "on" : ""}`} onClick={() => setFilter(c.key)} style={{ "--chip": c.color }}>
                <span className="chip-dot" /> {c.label} <span className="chip-count">{n}</span>
              </button>
            );
          })}
        </div>

        <div className="mail-list">
          {shown.map((e, i) => {
            const cat = CATEGORIES.find((c) => c.key === e.cat);
            return (
              <button key={e.id} className={`mail-row ${e.unread ? "unread" : ""} ${selected === e.id ? "sel" : ""}`} style={{ animationDelay: `${i * 45}ms` }} onClick={() => setSelected(e.id)}>
                <span className="mail-avatar" style={{ background: cat?.color }}>{e.initials}</span>
                <div className="mail-body">
                  <div className="mail-line1">
                    <span className="mail-from">{e.from}</span>
                    <span className="mail-time">{e.time}</span>
                  </div>
                  <div className="mail-line2">
                    <span className="mail-subject">
                      {e.star && <Star size={13} className="ic-star" fill="#D97706" stroke="#D97706" />}
                      {e.subject}
                    </span>
                    {e.attach && <Paperclip size={13} className="ic-attach" />}
                  </div>
                  <p className="mail-preview">{e.preview}</p>
                </div>
                {e.unread && <span className="unread-dot" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* RIGHT: reading pane */}
      <div className="inbox-right">
        {openEmail ? (
          <ReadingPane
            email={openEmail}
            onClose={() => setSelected(null)}
            onFeature={onFeature}
            onUnavailable={onUnavailable}
          />
        ) : (
          <div className="reader-empty">
            <div className="reader-empty-icon"><InboxIcon size={40} strokeWidth={1.6} /></div>
            <h3>Select an email to read</h3>
            <p>Choose a message from your inbox to view it here and try the AI tools.</p>
          </div>
        )}
      </div>
    </div>
  );
}
