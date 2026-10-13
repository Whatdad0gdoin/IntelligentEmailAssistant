/**
 * Attachments on the open message: what is attached, and how to open it.
 *
 * Nothing here interprets a file. Text from attached documents is extracted on
 * the server and folded into the summary; images are not described at all.
 * The user opens the attachment and looks at it, which for a picture is both
 * cheaper and more honest than having a model narrate it.
 *
 * Two things this has to get right, both honesty problems rather than layout
 * problems.
 *
 * First, an attachment whose text could not be read must say so. A row showing
 * only a filename implies the assistant took the file into account; if the PDF
 * was a scan with no text layer, it did not, and the summary above is missing
 * whatever was in it.
 *
 * Second, the file is fetched, never linked. The JWT travels as a header and a
 * browser will not attach one to <img src> or <a href>, so every preview and
 * every download goes through the api client and renders from a blob: URL.
 * Object URLs are revoked when the row closes or unmounts; leaking them would
 * keep email content alive in the tab after the user navigated away, which is
 * the spirit of NFR-03 even though the constraint is written about the server.
 */

import { useEffect, useRef, useState } from "react";
import {
  Download, Eye, EyeOff, FileText, FileWarning, Image as ImageIcon, Loader2,
  Paperclip,
} from "lucide-react";

import * as api from "../api/client.js";

/** Bytes to something a person reads. */
function formatSize(bytes) {
  if (!bytes || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * What the row says about itself, per backend status.
 *
 * `read` drives the styling: whether the assistant actually took this file's
 * content into account. It is the one thing a reader needs at a glance, and
 * an image is honestly "no" -- it is attached, the summary does not know what
 * is in it, and the user can open it.
 */
function describe(item) {
  switch (item.status) {
    case "extracted":
      return {
        read: true,
        icon: FileText,
        note: item.truncated ? "Text read (truncated)" : "Text read",
      };
    case "image":
      return { read: false, icon: ImageIcon, note: "Image — open to view" };
    case "empty":
      return { read: false, icon: FileWarning, note: item.detail || "No text in this file" };
    case "too_large":
      return { read: false, icon: FileWarning, note: "Too large to open" };
    case "encrypted":
      return { read: false, icon: FileWarning, note: "Password protected" };
    case "no_extractor":
      return { read: false, icon: FileWarning, note: item.detail || "Text not read" };
    case "failed":
      return { read: false, icon: FileWarning, note: "Could not be read" };
    case "unsupported":
      return { read: false, icon: FileWarning, note: "Text not read" };
    default:
      return { read: false, icon: FileWarning, note: item.detail || "Attached" };
  }
}

/** Which element can display this type once it is a blob. */
function previewKind(contentType) {
  const type = (contentType || "").toLowerCase().split(";")[0].trim();
  if (type.startsWith("image/")) return "image";
  if (type === "application/pdf") return "pdf";
  if (type === "text/plain" || type === "text/csv") return "text";
  return null;
}

function AttachmentRow({ item, emailId }) {
  const [objectUrl, setObjectUrl] = useState(null);
  const [textPreview, setTextPreview] = useState(null);
  const [state, setState] = useState("idle");
  const [error, setError] = useState(null);
  // Held in a ref as well as state so cleanup can revoke the current URL
  // without the effect re-running every time it changes.
  const urlRef = useRef(null);

  const meta = describe(item);
  const Icon = meta.icon;
  const kind = previewKind(item.content_type);

  function release() {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setObjectUrl(null);
    setTextPreview(null);
  }

  // Revoke on unmount and whenever a different email is opened.
  useEffect(() => release, []);

  async function load() {
    const blob = await api.fetchAttachment(emailId, item.id);
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    return { blob, url };
  }

  async function togglePreview() {
    if (objectUrl || textPreview) {
      release();
      return;
    }
    if (state === "loading") return;
    setState("loading");
    setError(null);
    try {
      const { blob, url } = await load();
      // Text is read into a string rather than framed, so it renders in the
      // page's own typography and cannot be a document in its own right.
      if (kind === "text") {
        setTextPreview((await blob.text()).slice(0, 20000));
        URL.revokeObjectURL(url);
        urlRef.current = null;
      } else {
        setObjectUrl(url);
      }
      setState("idle");
    } catch (err) {
      setError(err.message);
      setState("error");
    }
  }

  /** Hand the already-fetched blob to a new tab.
   *
   * The fallback for a browser whose PDF viewer will not run in a frame, or
   * a PDF the viewer chokes on. The tab is opened from the existing object
   * URL rather than the API path, because a new tab cannot carry the
   * Authorization header any more than an <img> can.
   */
  function openInTab() {
    if (urlRef.current) window.open(urlRef.current, "_blank", "noopener");
  }

  async function download() {
    if (state === "downloading") return;
    setState("downloading");
    setError(null);
    try {
      const blob = await api.fetchAttachment(emailId, item.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = item.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // The browser has taken its copy by the time click() returns.
      URL.revokeObjectURL(url);
      setState("idle");
    } catch (err) {
      setError(err.message);
      setState("error");
    }
  }

  const open = Boolean(objectUrl || textPreview);
  const busy = state === "loading";

  return (
    <li className={`attach-row ${meta.read ? "read" : "unread"}`}>
      <div className="attach-main">
        <Icon size={15} strokeWidth={2.1} className="attach-icon" />
        <span className="attach-name" title={item.filename}>{item.filename}</span>
        <span className="attach-size">{formatSize(item.size_bytes)}</span>
        <span className={`attach-note ${meta.read ? "ok" : ""}`}>{meta.note}</span>

        <div className="attach-buttons">
          {/* Offered only for types the backend will serve inline. Anything
              else -- a .docx, a .zip, and critically anything the browser
              would execute as markup -- is download-only. */}
          {item.can_preview && kind && (
            <button
              className="attach-btn"
              onClick={togglePreview}
              disabled={busy}
              aria-expanded={open}
            >
              {busy
                ? <Loader2 size={14} strokeWidth={2.2} className="spin" />
                : open
                  ? <EyeOff size={14} strokeWidth={2.2} />
                  : <Eye size={14} strokeWidth={2.2} />}
              <span>{open ? "Hide" : "View"}</span>
            </button>
          )}
          {item.can_open && (
            <button
              className="attach-btn"
              onClick={download}
              disabled={state === "downloading"}
              aria-label={`Download ${item.filename}`}
            >
              {state === "downloading"
                ? <Loader2 size={14} strokeWidth={2.2} className="spin" />
                : <Download size={14} strokeWidth={2.2} />}
              <span>Save</span>
            </button>
          )}
        </div>
      </div>

      {error && <p className="ai-error attach-error">{error}</p>}

      {objectUrl && kind === "image" && (
        <div className="attach-preview">
          <img src={objectUrl} alt={item.filename} className="attach-image" />
        </div>
      )}

      {objectUrl && kind === "pdf" && (
        <div className="attach-preview">
          {/* No sandbox attribute, deliberately, after an earlier version
              shipped sandbox="" and rendered a broken-file icon instead of
              the document.

              A bare sandbox revokes every permission, and the browser's PDF
              viewer is itself a scripted, same-origin application -- Chrome's
              and Firefox's both refuse to start without allow-scripts and
              allow-same-origin. Granting that pair back is equivalent to no
              sandbox at all for same-origin content, so writing it out would
              be security theatre rather than security.

              What actually contains this: the browser's PDF viewer runs in
              its own hardened process, which is a stronger boundary than an
              iframe attribute. And the frame can only ever hold a PDF -- the
              server sends application/pdf only for allowlisted types
              (INLINE_SAFE_TYPES) and previewKind() only returns "pdf" for
              that same type, so sender-supplied HTML cannot reach here. */}
          <iframe
            src={objectUrl}
            title={item.filename}
            className="attach-pdf"
          />
          <p className="attach-fallback">
            Not showing?{" "}
            <button className="attach-link" onClick={openInTab}>
              Open in a new tab
            </button>{" "}
            or use Save.
          </p>
        </div>
      )}

      {textPreview !== null && (
        <div className="attach-preview">
          <pre className="attach-text">{textPreview}</pre>
        </div>
      )}
    </li>
  );
}

export default function AttachmentList({ attachments = [], emailId }) {
  if (!attachments.length) return null;

  const unread = attachments.filter((a) => describe(a).read === false).length;

  return (
    <section className="attach-panel">
      <header className="attach-head">
        <Paperclip size={14} strokeWidth={2.4} />
        <b>
          {attachments.length} attachment{attachments.length === 1 ? "" : "s"}
        </b>
        {/* Stated up front rather than left to be inferred row by row: if the
            summary above is missing something, this is the warning. */}
        {unread > 0 && (
          <span className="attach-warn">
            {unread} not included in the summary
          </span>
        )}
      </header>
      <ul className="attach-list">
        {attachments.map((item) => (
          // Keyed on the email too, so switching messages builds fresh rows
          // rather than reusing one that is still holding a blob: URL.
          <AttachmentRow key={`${emailId}:${item.id}`} item={item} emailId={emailId} />
        ))}
      </ul>
    </section>
  );
}
