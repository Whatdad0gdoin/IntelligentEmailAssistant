/**
 * Auth state for the SPA (NFR-04, section 5.1).
 *
 * The JWT itself lives in the api client's module scope; this hook holds only
 * the derived UI state (who is signed in). A 401 from any request clears both.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import * as api from "../api/client.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [expiredNotice, setExpiredNotice] = useState(false);

  // Any 401, from any call anywhere in the app, lands here.
  useEffect(() => {
    api.setUnauthorizedHandler(() => {
      setUser(null);
      setExpiredNotice(true);
    });
    return () => api.setUnauthorizedHandler(null);
  }, []);

  const signIn = useCallback(async (email, password) => {
    const { token } = await api.login(email, password);
    api.setToken(token);
    setUser({ email });
    setExpiredNotice(false);
  }, []);

  const signOut = useCallback(() => {
    api.clearToken();
    setUser(null);
    setExpiredNotice(false);
  }, []);

  const value = useMemo(
    () => ({ user, signIn, signOut, expiredNotice, dismissExpiredNotice: () => setExpiredNotice(false) }),
    [user, signIn, signOut, expiredNotice]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside an <AuthProvider>");
  return ctx;
}
