/**
 * Inbox view (FR-08).
 *
 * Renders the five buckets the server already grouped: Work, Personal,
 * Promotions, Studies and Review. The user does no sorting -- that is the
 * requirement. The categories and quick filters in the sidebar (Dashboard
 * holds the choice) decide which mail is shown; they narrow the view rather
 * than reordering it, so the grouping always holds.
 *
 * Review carries its explanation inline (section 4.3): an email lands there
 * when the classifier's evidence failed verification or its confidence was
 * below threshold. It is never a silent fallback to Work.
 *
 * Layout: the list has the whole page until an email is open. Opening one
 * marks the split `has-selection`, and the stylesheet brings the list in to
 * its column while the reading pane widens beside it. On a narrow window the
 * same class swaps the list for the reader instead. There is no "select an
 * email" card: a pane with nothing in it takes no room.
 */

import { useState } from "react";
import { AlertCircle, Paperclip, Search, X } from "lucide-react";

import ReadingPane from "../components/ReadingPane.jsx";
import { CATEGORIES, REVIEW_CATEGORY } from "../lib/constants.js";
import { formatReceived } from "../lib/format.js";
import { matchesQuery, normaliseQuery, selectView } from "../lib/search.js";

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
  const attachmentCount = Array.isArray(email.attachments) ? email.attachments.length : 0;
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
          {attachmentCount > 0 && (
            <span
              className="mail-clip"
              role="img"
              aria-label={`${attachmentCount} ${attachmentCount === 1 ? "attachment" : "attachments"}`}
              title={`${attachmentCount} ${attachmentCount === 1 ? "attachment" : "attachments"}`}
            >
              <Paperclip size={13} strokeWidth={2.2} aria-hidden="true" />
            </span>
          )}
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
  voiceEnabled,
  translationLang,
  speechLang,
}) {
  const [query, setQuery] = useState("");

  const total = GROUP_ORDER.reduce((n, g) => n + (groups[g]?.length || 0), 0);

  const q = normaliseQuery(query);
  const matches = (email) => matchesQuery(email, q);


  // "All", a quick filter and any search render as one flat list. Choosing a
  // category shows that category and nothing else, still headed so Review
  // keeps its explanation. Decided in lib/search.js so it can be tested
  // without a browser: the bug this replaces (every group rendering regardless
  // of the chosen category) was invisible in the JSX.
  const view = selectView({ groups, order: GROUP_ORDER, filter, query });
  const searching = view.searching;
  const showFlat = view.mode === "flat";
  const flatList = view.list;
  const groupedNames = view.names;
  // A chosen category or filter with nothing in it shows a message in place of
  // a bare heading. An empty mailbox says so once, not once for the mailbox
  // and again for whichever category happens to be chosen.
  const nothingHere = Boolean(view.empty);
  const selectedIsEmpty = nothingHere && total > 0;

  let rowIndex = 0;

  // The split follows the email that is actually open, not the id chosen. An
  // id that matches nothing, as after the mailbox is reloaded or changed, has
  // no reader to show, and would shrink the list beside a blank.
  return (
    <div className={`inbox-split ${openEmail ? "has-selection" : ""}`}>
      <div className="inbox-left">
        <header className="main-head">
          <div>
            <h1 className="main-title">Inbox</h1>
            {loading && <p className="main-sub">Classifying…</p>}
          </div>
        </header>

        <div className="search-box wide">
          <Search size={16} className="search-icon" />
          <input
            type="search"
            placeholder="Search mail…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search mail"
          />
          {searching && (
            <button className="search-clear" onClick={() => setQuery("")} aria-label="Clear search">
              <X size={15} />
            </button>
          )}
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

        {/* The way back is here as well as in the sidebar, which is only icons
            on a narrow window. */}
        {!loading && !error && selectedIsEmpty && (
          <div className="reader-empty">
            <h3>{view.emptyTitle || `Nothing in ${filter}`}</h3>
            <p>Choose another category or filter in the sidebar, or go back to the whole inbox.</p>
            <button className="chip" onClick={() => setFilter("all")}>Show all mail</button>
          </div>
        )}

        {!loading && !error && total === 0 && (
          <div className="reader-empty"><h3>No emails</h3><p>The mailbox is empty.</p></div>
        )}

        {!loading && !error && searching && (
          <p className="search-summary">
            {flatList.length === 0
              ? "No messages match"
              : `${flatList.length} ${flatList.length === 1 ? "message" : "messages"} matching`}{" "}
            <b>“{query.trim()}”</b>
          </p>
        )}

        {/* A quick filter says which one it is, as a category's heading does. */}
        {!loading && !error && showFlat && view.heading && !nothingHere && (
          <h2 className="mail-group-head">
            {view.heading}
            <span className="mail-group-count">{flatList.length}</span>
          </h2>
        )}

        {/* One flat list: a search result set, a quick filter, or the "All" view. */}
        {!loading && !error && showFlat && !nothingHere && (
          <div className="mail-list">
            {flatList.map((email) => (
              <MailRow
                key={email.id}
                email={email}
                index={rowIndex++}
                selected={selected === email.id}
                onSelect={setSelected}
              />
            ))}
          </div>
        )}

        {/* A single category, still headed so the Review explanation has a home. */}
        {!loading && !error && !nothingHere && groupedNames.map((name) => (
          <section className="mail-group" key={name}>
            <h2 className="mail-group-head" style={{ "--c": COLOR_BY_LABEL[name] }}>
              <span className="chip-dot" />
              {name}
              <span className="mail-group-count">{(groups[name] || []).filter(matches).length}</span>
            </h2>
            {name === "Review" && (
              <p className="mail-group-note">
                Low confidence, unverified label - these were not filed automatically.
              </p>
            )}
            <div className="mail-list">
              {(groups[name] || []).filter(matches).map((email) => (
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

      {/* Always in the page, and empty until an email is open. The stylesheet
          keeps it at no width and widens it when the split is marked; a pane
          that only appeared then would have nothing to grow from, and the
          change would be a jump. */}
      <div className="inbox-right">
        {openEmail && (
          <ReadingPane
            email={openEmail}
            body={openBody}
            bodyLoading={bodyLoading}
            pendingAction={pendingAction}
            onActionConsumed={onActionConsumed}
            onBack={() => setSelected(null)}
            voiceEnabled={voiceEnabled}
            translationLang={translationLang}
            speechLang={speechLang}
          />
        )}
      </div>
    </div>
  );
}
