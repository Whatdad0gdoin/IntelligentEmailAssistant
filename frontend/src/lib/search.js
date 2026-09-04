/**
 * Inbox search.
 *
 * Runs entirely over the emails the server already sent, so typing costs no
 * request and no API budget. It is a filter, not a ranking: the point is to
 * find a message you know exists, not to guess relevance.
 *
 * Only fields a person actually scans are searched - sender, subject and the
 * preview line. Bodies are deliberately excluded: the list endpoint returns
 * snippets only (NFR-03 keeps bodies off the client until a message is opened),
 * so searching bodies would silently match only whatever happens to be cached
 * and give inconsistent results.
 */

const FIELDS = ["sender_name", "sender", "subject", "snippet"];

/** Normalised query, or "" when the query is only whitespace. */
export function normaliseQuery(query) {
  return (query || "").trim().toLowerCase();
}

/**
 * True when `email` matches `query`. An empty query matches everything, so a
 * cleared search box shows the full inbox rather than nothing.
 */
export function matchesQuery(email, query) {
  const q = normaliseQuery(query);
  if (!q) return true;
  if (!email) return false;
  return FIELDS.some((field) => {
    const value = email[field];
    return typeof value === "string" && value.toLowerCase().includes(q);
  });
}

/** Newest first, matching how the adapter orders the mailbox. */
export function newestFirst(a, b) {
  return new Date(b.received_at) - new Date(a.received_at);
}

/** Filter and order a list of emails for display. */
export function searchEmails(emails, query) {
  return (emails || []).filter((e) => matchesQuery(e, query)).sort(newestFirst);
}

/**
 * Decide what the inbox should render.
 *
 * Extracted from the view because the bug it replaces was invisible there: the
 * grouped branch listed every category with a match instead of the selected
 * one, so clicking "Promotions" showed the whole inbox. Logic that decides
 * what a user sees is worth testing without a browser.
 *
 * Returns either a flat list (All, or any search) or exactly one named group.
 */
export function selectView({ groups, order, filter, query }) {
  const q = normaliseQuery(query);
  const searching = q.length > 0;
  const flat = searching || filter === "all";

  if (flat) {
    const all = order.flatMap((name) => groups[name] || []);
    return { mode: "flat", searching, list: searchEmails(all, q), names: [] };
  }
  return {
    mode: "grouped",
    searching,
    list: [],
    names: order.filter((name) => name === filter),
    empty: (groups[filter] || []).length === 0,
  };
}
