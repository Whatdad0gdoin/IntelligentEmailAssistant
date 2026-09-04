/**
 * A user preference that survives a reload.
 *
 * Preferences are the one thing this app is allowed to keep in localStorage.
 * The JWT is deliberately memory-only (section 5.1) and no email content ever
 * touches storage (NFR-03); a boolean like "voice on" carries neither risk, and
 * a setting that resets on every refresh is not a setting.
 *
 * Every storage access is wrapped: private windows and some browser policies
 * throw on the accessor itself, and a settings toggle must never take the app
 * down with it.
 */

import { useCallback, useState } from "react";

const PREFIX = "mailkit:";

function read(key, fallback) {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Storage unavailable: the preference still applies for this session.
  }
}

export function usePreference(key, fallback) {
  const [value, setValue] = useState(() => read(key, fallback));

  const update = useCallback(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? next(prev) : next;
        write(key, resolved);
        return resolved;
      });
    },
    [key]
  );

  return [value, update];
}
