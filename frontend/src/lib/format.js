/**
 * Display formatting.
 *
 * received_at arrives as ISO-8601 parsed from the Date header (rule 5: the
 * model never touches it). Turning that into "9:24 AM" or "Mon" is a rendering
 * concern, so it happens here rather than on the server.
 */

const TIME = { hour: "numeric", minute: "2-digit" };
const WEEKDAY = { weekday: "short" };
const DATE = { day: "numeric", month: "short" };

export function formatReceived(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.floor((startOfToday - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);

  if (days <= 0) return d.toLocaleTimeString([], TIME);
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString([], WEEKDAY);
  return d.toLocaleDateString([], DATE);
}

/** Longer form for the reading pane header. */
export function formatReceivedLong(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}
