/**
 * Inbox view (FR-08).
 *
 * Renders the five buckets the server already grouped: Work, Personal,
 * Promotions, Studies and Review. The user does no sorting -- that is the
 * requirement. The category chips filter which groups are shown; they narrow
 * the view rather than reordering it, so the grouping always holds.
 *
 * Review carries its explanation inline (section 4.3): an email lands there
 * when the classifier's evidence failed verification or its confidence was
 * below threshold. It is never a silent fallback to Work.
 */

import { AlertCircle, Bell, Inbox as InboxIcon, Search } from "lucide-react";

import ReadingPane from "../components/ReadingPane.jsx";
import { CATEGORIES, REVIEW_CATEGORY } from "../lib/constants.js";
import { formatReceived } from "../lib/format.js";

const GROUP_ORDER = ["Work", "Personal", "Promotions", "Studies", "Review"];

const COLOR_BY_LABEL = CATEGORIES.reduce((acc, c) => {
  acc[c.label] = c.color;
  return acc;
}, { Review: REVIEW_CATEGORY.color });

/** NFR-01 mitigation: the inbox classifies on load, so show real structure
 *  while that round trip is in flight rather than an empty screen. */
function InboxSkeleton() {
  return (
    <div className="mail-list" aria-busy="true" aria-label="Loading inbox">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div className="mail-row skel" key={i} style={{ animationDelay: `${i * 60}ms` }}>
          <span className="skel-avatar" />
          <div className="mail-body">
            <span className="skel-line w40" />
            <span className="skel-line w70" />
            <span className="skel-line w90" />
          </div>
        </div>
      ))}
    </div>
  );
}

function MailRow({ email, selected, onSelect, index }) {
  const color = COLOR_BY_LABEL[email.category] || REVIEW_CATEGORY.color;
  const initials = (email.sender_name || email.sender || "?").slice(0, 2).toUpperCase();
  return (
    <button
      className={`mail-row ${email.unread ? "unread" : ""} ${selected ? "sel" : ""}`}
      style={{ animationDelay: `${index * 45}ms` }}
      onClick={() => onSelect(email.id)}
    >
      <span className="mail-avatar" style={{ background: color }}>{initials}</span>
      <div className="mail-body">
        <div className="mail-line1">
          <span className="mail-from">{email.sender_name || email.sender}</span>
          <span className="mail-time">{formatReceived(email.received_at)}</span>
        </div>
        <div className="mail-line2">
          <span className="mail-subject">{email.subject}</span>
        </div>
        <p className="mail-preview">{email.snippet}</p>
      </div>
      {email.unread && <span className="unread-dot" />}
    </button>
  );
}

export default function Inbox({
  groups,
  loading,
  error,
  filter,
  setFilter,
  selected,
  setSelected,
  openEmail,
  openBody,
  bodyLoading,
  onRetry,
  pendingAction,
  onActionConsumed,
}) {
  const total = GROUP_ORDER.reduce((n, g) => n + (groups[g]?.length || 0), 0);
  const unreadCount = GROUP_ORDER.reduce(
    (n, g) => n + (groups[g] || []).filter((e) => e.unread).length,
    0
  );

  const visibleGroups = GROUP_ORDER.filter((name) => {
    if ((groups[name] || []).length === 0) return false;
    return filter === "all" || filter === name;
  });

  let rowIndex = 0;

  return (
    <div className={`inbox-split ${selected ? "has-selection" : ""}`}>
      <div className="inbox-left">
        <header className="main-head">
          <div>
            <h1 className="main-title">Inbox</h1>
            <p className="main-sub">
              {loading ? "Classifying…" : `${unreadCount} unread · ${total} total`}
            </p>
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
            All <span className="chip-count">{total}</span>
          </button>
          {GROUP_ORDER.map((name) => {
            const n = (groups[name] || []).length;
            if (n === 0) return null;
            return (
              <button
                key={name}
                className={`chip ${filter === name ? "on" : ""}`}
                onClick={() => setFilter(name)}
                style={{ "--chip": COLOR_BY_LABEL[name] }}
              >
                <span className="chip-dot" /> {name} <span className="chip-count">{n}</span>
              </button>
            );
          })}
        </div>

        {loading && <InboxSkeleton />}

        {error && !loading && (
          <div className="inbox-error" role="alert">
            <AlertCircle size={18} />
            <div>
              <b>Could not load your inbox.</b>
              <p>{error}</p>
              <button className="chip" onClick={onRetry}>Try again</button>
            </div>
          </div>
        )}

        {!loading && !error && total === 0 && (
          <div className="reader-empty"><h3>No emails</h3><p>The mailbox is empty.</p></div>
        )}

        {!loading && !error && visibleGroups.map((name) => (
          <section className="mail-group" key={name}>
            <h2 className="mail-group-head" style={{ "--c": COLOR_BY_LABEL[name] }}>
              <span className="chip-dot" />
              {name}
              <span className="mail-group-count">{groups[name].length}</span>
            </h2>
            {name === "Review" && (
              <p className="mail-group-note">
                Low confidence, unverified label - these were not filed automatically.
              </p>
            )}
            <div className="mail-list">
              {groups[name].map((email) => (
                <MailRow
                  key={email.id}
                  email={email}
                  index={rowIndex++}
                  selected={selected === email.id}
                  onSelect={setSelected}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="inbox-right">
        {openEmail ? (
          <ReadingPane
            email={openEmail}
            body={openBody}
            bodyLoading={bodyLoading}
            pendingAction={pendingAction}
            onActionConsumed={onActionConsumed}
          />
        ) : (
          <div className="reader-empty">
            <div className="reader-empty-icon"><InboxIcon size={40} strokeWidth={1.6} /></div>
            <h3>Select an email to read</h3>
            <p>Choose a message to view it here and use the AI tools on it.</p>
          </div>
        )}
      </div>
    </div>
  );
}
