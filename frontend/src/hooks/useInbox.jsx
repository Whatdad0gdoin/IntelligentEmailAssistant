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
 *
 * Every function returned here has a stable identity, and the returned object
 * is memoised. That is not tidiness: Dashboard has an effect keyed on
 * `loadBody`, and an earlier version rebuilt both on every render, so the
 * effect re-ran on every keystroke in the search box.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as api from "../api/client.js";

const EMPTY = { Work: [], Personal: [], Promotions: [], Studies: [], Review: [] };

export function useInbox(enabled) {
  const [groups, setGroups] = useState(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [bodies, setBodies] = useState({});
  const [bodyLoading, setBodyLoading] = useState(false);

  // Read through refs inside loadBody so it never has to be recreated when the
  // cache changes. Recreating it would ripple into every effect that lists it.
  const bodiesRef = useRef(bodies);
  bodiesRef.current = bodies;
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

  const loadBody = useCallback(async (emailId) => {
    if (!emailId || bodiesRef.current[emailId] !== undefined || inFlight.current.has(emailId)) {
      return;
    }
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
  }, []);

  // One flat lookup table, rebuilt only when the groups change, instead of a
  // linear scan through five arrays on every call.
  const byId = useMemo(() => {
    const table = new Map();
    for (const list of Object.values(groups)) {
      for (const email of list) table.set(email.id, email);
    }
    return table;
  }, [groups]);

  const findEmail = useCallback((id) => byId.get(id) || null, [byId]);

  return useMemo(
    () => ({ groups, loading, error, reload: load, bodies, bodyLoading, loadBody, findEmail }),
    [groups, loading, error, load, bodies, bodyLoading, loadBody, findEmail]
  );
}
