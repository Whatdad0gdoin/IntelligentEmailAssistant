/**
 * Attachments on the open message: what is attached, and a way to open it.
 *
 * The list itself is the email's `attachments` from the inbox: name, type and
 * size, with no content. Nothing is fetched to render it, so a message with
 * ten attachments costs nothing until the user asks for one.
 *
 * View and Save each fetch one attachment, by its position in that list, from
 * GET /api/inbox/:id/attachments/:index. Attachments are never sent to the AI:
 * nothing here calls a summarise, draft or translate route, and the backend
 * keeps attachment content out of every prompt.
 *
 * Three rules shape the code below.
 *
 *  - Fetched, never linked. The JWT travels as a header, and a browser does
 *    not put a header on <img src> or <a href>. So the bytes come through the
 *    API client and are shown or saved from a blob: URL.
 *  - The server decides what is shown. Everything here was chosen by whoever
 *    sent the email. The backend serves only raster images, PDFs and plain
 *    text under their own type, and everything else as an opaque download, so
 *    the type on the Blob that comes back -- not the type the list claimed --
 *    picks the element. A sender's HTML or SVG never becomes a page here.
 *  - Nothing outlives its use. A blob: URL keeps the file alive in the tab, so
 *    it is revoked when the preview closes, when another opens, when the email
 *    changes and when the pane unmounts (NFR-03, in spirit: the constraint is
 *    written about the server).
 *
 * The PDF frame has no sandbox attribute on purpose. The browser's own PDF
 * viewer is a scripted, same-origin application and renders nothing in a
 * sandboxed frame; granting it back allow-scripts and allow-same-origin would
 * amount to no sandbox while looking like one. What contains the frame is that
 * only a Blob the server labelled application/pdf is ever put in it.
 */

import { useEffect, useRef, useState } from "react";
import {
  Download, Eye, EyeOff, File as FileIcon, FileImage, FileText, Loader2, Mail, X,
} from "lucide-react";

import * as api from "../api/client.js";
import { attachmentLabel, formatBytes } from "../lib/format.js";

// The types the backend serves under their own type (INLINE_TYPES in
// backend/routes/attachments.py), and the element each is shown in.
const PREVIEW_KIND = {
  "image/png": "image",
  "image/jpeg": "image",
  "image/gif": "image",
  "image/webp": "image",
  "image/bmp": "image",
  "application/pdf": "pdf",
  "text/plain": "text",
  "text/csv": "text",
};

// A text file is shown up to this many characters. The rest is one Save away.
const TEXT_PREVIEW_CHARS = 20000;

const NOT_SHOWABLE = "This file cannot be shown here. Use Save to download it.";

function previewKind(contentType) {
  return PREVIEW_KIND[(contentType || "").split(";")[0].trim().toLowerCase()] || null;
}

/** The name the browser saves under, including for a file the sender left unnamed. */
function downloadName(attachment) {
  if (attachment.filename) return attachment.filename;
  return attachment.content_type === "message/rfc822" ? "forwarded-message.eml" : "attachment";
}

function AttachmentIcon({ type }) {
  const t = type || "";
  let Icon = FileIcon;
  if (t.startsWith("image/")) Icon = FileImage;
  else if (t === "message/rfc822") Icon = Mail;
  else if (t === "application/pdf" || t.startsWith("text/") || /word|document/.test(t)) Icon = FileText;
  return <Icon size={14} strokeWidth={2.2} aria-hidden="true" />;
}

export default function Attachments({ emailId, attachments }) {
  // The one preview on screen: { index, kind, url } or { index, kind, text, clipped }.
  const [preview, setPreview] = useState(null);
  // The one fetch in flight: { index, action } where action is "view" or "save".
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);

  const previewUrl = useRef(null);
  const inFlight = useRef(null);
  // Bumped when the email changes or the pane goes away, so work that was
  // started for the old email can tell it is no longer wanted.
  const epoch = useRef(0);

  function releasePreviewUrl() {
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = null;
  }

  // A different email, or no pane at all: nothing fetched for the old one may
  // land, and nothing it was showing may stay alive.
  useEffect(() => {
    setPreview(null);
    setPending(null);
    setError(null);
    return () => {
      epoch.current += 1;
      if (inFlight.current) inFlight.current.abort();
      inFlight.current = null;
      releasePreviewUrl();
    };
  }, [emailId]);

  const list = Array.isArray(attachments) ? attachments : [];
  if (list.length === 0) return null;

  // One attachment's bytes, or null when the fetch failed or no longer matters.
  // One fetch at a time: a second click while one is in flight does nothing.
  async function fetchOne(index, action) {
    if (inFlight.current) return null;
    const controller = new AbortController();
    inFlight.current = controller;
    setPending({ index, action });
    setError(null);
    try {
      const blob = await api.fetchAttachment(emailId, index, { signal: controller.signal });
      return controller.signal.aborted ? null : blob;
    } catch (err) {
      if (!controller.signal.aborted) setError({ index, message: err.message });
      return null;
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setPending(null);
      }
    }
  }

  function closePreview() {
    releasePreviewUrl();
    setPreview(null);
  }

  async function view(index) {
    if (preview && preview.index === index) {
      closePreview();
      return;
    }
    const started = epoch.current;
    const blob = await fetchOne(index, "view");
    if (!blob) return;
    // What the server sent decides, not what the list said (see the header).
    const kind = previewKind(blob.type);
    if (!kind) {
      setError({ index, message: NOT_SHOWABLE });
      return;
    }
    if (kind === "text") {
      const text = await blob.text();
      if (epoch.current !== started) return;
      releasePreviewUrl();
      setPreview({
        index, kind, text: text.slice(0, TEXT_PREVIEW_CHARS), clipped: text.length > TEXT_PREVIEW_CHARS,
      });
      return;
    }
    releasePreviewUrl();
    previewUrl.current = URL.createObjectURL(blob);
    setPreview({ index, kind, url: previewUrl.current });
  }

  async function save(index) {
    const blob = await fetchOne(index, "save");
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = downloadName(list[index]);
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Safe at once: the browser took its reference to the Blob when the click
    // resolved the URL, so the download does not need the URL to stay valid.
    URL.revokeObjectURL(url);
  }

  // For a browser that will not show a PDF in a frame. Opened from the blob:
  // URL already in hand, because a new tab cannot send the token either.
  function openInTab() {
    if (previewUrl.current) window.open(previewUrl.current, "_blank", "noopener");
  }

  const busy = pending !== null;
  const shown = preview && list[preview.index] ? attachmentLabel(list[preview.index]) : "";

  return (
    <div className="reader-attachments">
      <ul
        className="att-list"
        aria-label={`${list.length} ${list.length === 1 ? "attachment" : "attachments"}`}
      >
        {list.map((attachment, i) => {
          const label = attachmentLabel(attachment);
          const size = formatBytes(attachment.size);
          const open = preview !== null && preview.index === i;
          const viewing = busy && pending.index === i && pending.action === "view";
          const saving = busy && pending.index === i && pending.action === "save";
          return (
            <li className="att-chip" key={`${i}-${attachment.filename}`} title={label}>
              <AttachmentIcon type={attachment.content_type} />
              <span className="att-name">{label}</span>
              {size && <span className="att-size">{size}</span>}
              {/* Offered only for a type the backend will serve for showing.
                  Not disabled while a fetch runs: disabling the focused button
                  drops keyboard focus to the page. fetchOne ignores the click. */}
              {previewKind(attachment.content_type) && (
                <button
                  type="button"
                  className="att-btn"
                  onClick={() => view(i)}
                  aria-expanded={open}
                  aria-label={`${open ? "Hide" : "View"} ${label}`}
                  aria-disabled={busy || undefined}
                >
                  {viewing
                    ? <Loader2 size={13} strokeWidth={2.4} className="spin" aria-hidden="true" />
                    : open
                      ? <EyeOff size={13} strokeWidth={2.2} aria-hidden="true" />
                      : <Eye size={13} strokeWidth={2.2} aria-hidden="true" />}
                  <span>{open ? "Hide" : "View"}</span>
                </button>
              )}
              <button
                type="button"
                className="att-btn"
                onClick={() => save(i)}
                aria-label={`Save ${label}`}
                aria-disabled={busy || undefined}
              >
                {saving
                  ? <Loader2 size={13} strokeWidth={2.4} className="spin" aria-hidden="true" />
                  : <Download size={13} strokeWidth={2.2} aria-hidden="true" />}
                <span>Save</span>
              </button>
            </li>
          );
        })}
      </ul>

      {error && list[error.index] && (
        <p className="ai-error" role="alert">
          {attachmentLabel(list[error.index])}: {error.message}
        </p>
      )}

      {preview && (
        <div className="att-preview" role="region" aria-label={`Preview of ${shown}`}>
          <div className="att-preview-head">
            <span className="att-preview-name">{shown}</span>
            <button
              type="button"
              className="ai-close"
              onClick={closePreview}
              aria-label={`Close the preview of ${shown}`}
            >
              <X size={14} />
            </button>
          </div>

          {preview.kind === "image" && <img className="att-image" src={preview.url} alt={shown} />}

          {preview.kind === "pdf" && (
            <>
              <iframe className="att-pdf" src={preview.url} title={shown} />
              <p className="att-fallback">
                Not showing?{" "}
                <button type="button" className="att-link" onClick={openInTab}>Open it in a new tab</button>
                {" "}or use Save.
              </p>
            </>
          )}

          {preview.kind === "text" && (
            <>
              <pre className="att-text">{preview.text}</pre>
              {preview.clipped && (
                <p className="att-fallback">Only the start of this file is shown. Save it to read the rest.</p>
              )}
            </>
          )}
        </div>
      )}

      <p className="att-note">
        An attachment is fetched only when you open or save it, and is never sent to the AI.
      </p>
    </div>
  );
}
