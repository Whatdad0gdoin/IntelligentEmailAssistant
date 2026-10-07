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

const SIZE_UNITS = ["KB", "MB", "GB"];

/**
 * An attachment size the way mail clients show it: "640 B", "4.9 KB", "12 MB".
 * Binary units, one decimal below 10. A size the source did not report (null)
 * renders as nothing, because "0 B" would be a claim nobody made.
 */
export function formatBytes(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < SIZE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const shown = value < 10 ? value.toFixed(1).replace(/\.0$/, "") : String(Math.round(value));
  return `${shown} ${SIZE_UNITS[unit]}`;
}

/** What to call an attachment, including one the sender left unnamed. */
export function attachmentLabel(attachment) {
  if (attachment && attachment.filename) return attachment.filename;
  return attachment && attachment.content_type === "message/rfc822"
    ? "Forwarded message"
    : "Unnamed attachment";
}
