/**
 * Connect Gmail (Settings): how a user's own email gets into the app.
 *
 * Connecting opens Google's consent page in a popup. The page stays where it
 * is, because the sign-in token lives only in memory and leaving would sign
 * the user out (section 5.1). Google sends the popup back to the backend,
 * which stores the read-only token; this panel finds out by asking
 * GET /api/gmail every couple of seconds, and sooner when the popup's last
 * page can reach this tab.
 *
 * popup.closed is not used to stop waiting. Google's pages isolate the popup
 * from the window that opened it, so in some browsers it reads as closed
 * while the user is still choosing an account.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Mail } from "lucide-react";

import * as api from "../api/client.js";

const POLL_MS = 2000;
const WAIT_MS = 3 * 60 * 1000;

function connectedOn(iso) {
  const date = iso ? new Date(iso) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return ` Connected ${date.toLocaleDateString(undefined, { day: "numeric", month: "short" })}.`;
}

export default function GmailConnect({ onMailboxChanged }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [waiting, setWaiting] = useState(false);
  const [busy, setBusy] = useState(false);
  // Set when the browser blocked the popup: a link the user can click instead.
  const [manualUrl, setManualUrl] = useState(null);

  const timer = useRef(null);
  const deadline = useRef(0);
  const changed = useRef(onMailboxChanged);
  changed.current = onMailboxChanged;

  const stopWaiting = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = null;
    setWaiting(false);
    setManualUrl(null);
  }, []);

  const check = useCallback(async () => {
    try {
      const next = await api.gmailStatus();
      setStatus(next);
      if (next.connected && timer.current !== null) {
        stopWaiting();
        changed.current?.();
        return;
      }
    } catch (err) {
      if (err.status !== 401) setError(err.message);
    }
    if (timer.current !== null) {
      if (Date.now() > deadline.current) {
        stopWaiting();
        setError("Gmail did not finish connecting. Press Connect Gmail to try again.");
      } else {
        timer.current = setTimeout(check, POLL_MS);
      }
    }
  }, [stopWaiting]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const first = await api.gmailStatus();
        if (live) setStatus(first);
      } catch (err) {
        if (live && err.status !== 401) setError(err.message);
      }
    })();
    return () => {
      live = false;
      clearTimeout(timer.current);
    };
  }, []);

  // The popup's last page posts its result here when the browser allows it.
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return undefined;
    const channel = new BroadcastChannel("mailkit-gmail");
    channel.onmessage = (event) => {
      const result = event.data || {};
      if (result.ok) {
        clearTimeout(timer.current);
        timer.current = setTimeout(check, 0);
      } else {
        stopWaiting();
        setError(`${result.title || "Gmail was not connected"}. ${result.detail || ""}`.trim());
      }
    };
    return () => channel.close();
  }, [check, stopWaiting]);

  const connect = async () => {
    setError(null);
    // Opened inside the click, before any await: a popup opened after one is
    // treated as unrequested and blocked.
    const popup = window.open("", "mailkit-gmail", "popup,width=520,height=680");
    let url;
    try {
      ({ auth_url: url } = await api.gmailConnect());
    } catch (err) {
      popup?.close();
      setError(err.message);
      return;
    }
    if (popup) popup.location.href = url;
    else setManualUrl(url);
    deadline.current = Date.now() + WAIT_MS;
    setWaiting(true);
    timer.current = setTimeout(check, POLL_MS);
  };

  const disconnect = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.gmailDisconnect();
      setStatus(await api.gmailStatus());
      changed.current?.();
    } catch (err) {
      if (err.status !== 401) setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  let detail = "Checking…";
  let control = null;
  if (status && !status.available) {
    detail = "Not set up on this server yet, so you see the demo inbox. A teammate adds a Google OAuth client first (README: Let users connect their own Gmail).";
    control = <span className="setting-status off"><span className="setting-dot" />Unavailable</span>;
  } else if (status && status.connected) {
    detail = `Reading ${status.address}, read-only.${connectedOn(status.connected_at)}`;
    control = (
      <button className="action-btn" onClick={disconnect} disabled={busy}>
        {busy ? "Disconnecting" : "Disconnect"}
      </button>
    );
  } else if (status) {
    detail = "You are seeing the demo inbox. Connect Gmail to read your own email here.";
    control = (
      <button className="action-btn on" onClick={connect} disabled={waiting}>
        <Mail size={15} strokeWidth={2.2} />
        <span>{waiting ? "Waiting for Google" : "Connect Gmail"}</span>
      </button>
    );
  }

  return (
    <>
      <div className="setting-row">
        <div className="setting-text">
          <span className="setting-label"><Mail size={15} /> Gmail</span>
          <span className="setting-detail">{detail}</span>
        </div>
        <div className="setting-control">{control}</div>
      </div>

      {waiting && (
        <p className="setting-footnote" role="status">
          {manualUrl
            ? <>Your browser blocked the Google window. <a href={manualUrl} target="_blank" rel="noreferrer">Open Google sign-in</a>, then come back here. </>
            : "Finish in the Google window. This page updates by itself when you are done. "}
          <button className="card-switch" onClick={stopWaiting}>Cancel</button>
        </p>
      )}

      {error && (
        <div className="feature-error" role="alert">
          <b>Gmail</b>
          <span>{error}</span>
        </div>
      )}

      <p className="setting-footnote">
        Read-only: Google lets MailKit view your email, never send, delete or change it, and you
        can remove access here or in your Google account. Each email's text is sent to OpenAI to
        sort and summarise it, and is not stored. While MailKit is in testing, Google only lets
        addresses the team has added as test users connect, and ends each connection after 7
        days.
      </p>
    </>
  );
}
