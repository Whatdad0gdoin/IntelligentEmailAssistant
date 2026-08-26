/**
 * Inbox data (FR-08, NFR-01).
 *
 * One GET /api/inbox on login returns the mailbox already grouped, with
 * classification done server-side as a single batch. There is no per-email
 * classify call as the list renders.
 *
 * Bodies are fetched one at a time, only when a message is opened, and cached
 * for the session so re-opening the same email costs nothing. The cache lives
 * in component state and dies with the tab -- no email content is written to
 * localStorage or anywhere else that persists (NFR-03).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../api/client.js";

const EMPTY = { Work: [], Personal: [], Promotions: [], Studies: [], Review: [] };

export function useInbox(enabled) {
  const [groups, setGroups] = useState(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [bodies, setBodies] = useState({});
  const [bodyLoading, setBodyLoading] = useState(false);
  const inFlight = useRef(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.fetchInbox();
      setGroups({ ...EMPTY, ...(data.groups || {}) });
    } catch (err) {
      // A 401 is already handled by the client (it routes back to login), so
      // anything reaching here is a real failure worth showing.
      if (err.status !== 401) setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) load();
    else {
      setGroups(EMPTY);
      setBodies({});
      setError(null);
    }
  }, [enabled, load]);

  const loadBody = useCallback(
    async (emailId) => {
      if (!emailId || bodies[emailId] !== undefined || inFlight.current.has(emailId)) return;
      inFlight.current.add(emailId);
      setBodyLoading(true);
      try {
        const message = await api.getEmail(emailId);
        setBodies((prev) => ({ ...prev, [emailId]: message.body }));
      } catch (err) {
        if (err.status !== 401) setBodies((prev) => ({ ...prev, [emailId]: null }));
      } finally {
        inFlight.current.delete(emailId);
        setBodyLoading(false);
      }
    },
    [bodies]
  );

  const findEmail = useCallback(
    (id) => {
      for (const list of Object.values(groups)) {
        const hit = list.find((e) => e.id === id);
        if (hit) return hit;
      }
      return null;
    },
    [groups]
  );

  return { groups, loading, error, reload: load, bodies, bodyLoading, loadBody, findEmail };
}
