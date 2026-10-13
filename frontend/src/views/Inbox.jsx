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
 *
 * A row is a toggle: the open email's row closes it, and the list has the
 * page again. Closing is the opening run backwards, so the reader stays in
 * the pane, out of reach, until the list has finished widening over it.
 */

import { useEffect, useRef, useState } from "react";
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

/** How long a closed reader is kept when the split never says its slide has
 *  ended: the transition was cancelled, or the browser cannot animate a grid's
 *  columns. The stylesheet's slide is 0.5s, and this has to outlast it or the
 *  reader would go while it could still be seen (styles.test.js holds the two
 *  together). */
const CLOSE_FALLBACK_MS = 600;

/** Whether closing an email is animated in this window. These are the
 *  stylesheet's own two queries: it slides the split only where both panes
 *  fit, and not for anyone who asked for reduced motion. Where the question
 *  cannot be asked, nothing is assumed to move. */
function closeIsAnimated() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return !window.matchMedia("(max-width:1080px)").matches
    && !window.matchMedia("(prefers-reduced-motion:reduce)").matches;
}

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
  // aria-pressed says which row is open and that pressing it again closes it.
  // It is a state, not part of the name, so the row is still found by its
  // sender and subject.
  return (
    <button
      className={`mail-row ${email.unread ? "unread" : ""} ${selected ? "sel" : ""}`}
      style={{ animationDelay: `${index * 45}ms` }}
      aria-pressed={selected}
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

  // What the reading pane holds. `open` is the email that is open now. When
  // it stops being open on a window that animates, what the pane last held is
  // kept as `leaving`, so the same reader, with whatever it was showing, is
  // still there while the list widens back. It is worked out here, as the
  // change is rendered, and not in an effect: a render with the pane empty in
  // between would unmount the reader, and there would be nothing to slide away.
  const open = openEmail ? { email: openEmail, body: openBody, bodyLoading } : null;
  const [last, setLast] = useState(open);
  const [leaving, setLeaving] = useState(null);
  if (open) {
    if (!last || last.email !== open.email || last.body !== open.body || last.bodyLoading !== open.bodyLoading) {
      setLast(open);
    }
    // An email opened during a close takes the pane back, and the effect
    // below drops the removal it had pending.
    if (leaving) setLeaving(null);
  } else if (last) {
    setLast(null);
    if (closeIsAnimated()) setLeaving(last);
  }
  const reader = open || leaving;
  const closing = !open && leaving !== null;

  // The reader goes when the split says the list's column has finished
  // widening. That is the one transition that ends the slide: the gap ends
  // with it, and everything else that bubbles up to the split is a row or a
  // button finishing a hover. The timer is for when that is never said.
  const splitRef = useRef(null);
  useEffect(() => {
    if (!leaving) return undefined;
    const split = splitRef.current;
    const remove = () => setLeaving(null);
    const slideEnded = (event) => {
      if (event.target === split && event.propertyName === "grid-template-columns") remove();
    };
    split.addEventListener("transitionend", slideEnded);
    const timer = window.setTimeout(remove, CLOSE_FALLBACK_MS);
    return () => {
      split.removeEventListener("transitionend", slideEnded);
      window.clearTimeout(timer);
    };
  }, [leaving]);

  // A row is a toggle. Only a row is: a command goes through Dashboard's
  // runVoiceAction, which selects its email and so can never close one.
  const toggleEmail = (id) => setSelected(id === selected ? null : id);

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
  // no reader to show, and would shrink the list beside a blank. The mark goes
  // the moment an email is closed, which is what starts the list widening; the
  // reader it is closing over is taken out when that has finished.
  return (
    <div ref={splitRef} className={`inbox-split ${openEmail ? "has-selection" : ""}`}>
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
                onSelect={toggleEmail}
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
                  onSelect={toggleEmail}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      {/* Always in the page, and empty until an email is open. The stylesheet
          keeps it at no width and widens it when the split is marked; a pane
          that only appeared then would have nothing to grow from, and the
          change would be a jump.

          A reader on its way out is not there to be used. `inert` takes it
          out of the tab order, away from the pointer and out of the
          accessibility tree, and aria-hidden says the last of those again for
          anything that does not know `inert`. It is written as an empty
          string because React 18 passes that through as the attribute and
          drops `true`; React 19 reads it the other way round. A command is
          never handed to a reader that is leaving. */}
      <div className="inbox-right" inert={closing ? "" : undefined} aria-hidden={closing ? "true" : undefined}>
        {reader && (
          <ReadingPane
            email={reader.email}
            body={reader.body}
            bodyLoading={reader.bodyLoading}
            pendingAction={closing ? null : pendingAction}
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
