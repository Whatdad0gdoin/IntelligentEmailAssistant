/**
 * Login view (NFR-04, section 5.1).
 *
 * Adapted from the teammate's LoginPage. The hero panel, card layout and all
 * CSS classes are unchanged. What changed is the part that was fake:
 *
 *   before:  setTimeout(() => onLogin(email), 900)   // accepted anything
 *   after:   await signIn(email, password)           // POST /api/auth/login
 *
 * The three copy lines that advertised "any input is accepted" have been
 * rewritten, because they are no longer true and leaving them would misdescribe
 * the build.
 */

import { useEffect, useState } from "react";
import { ArrowRight, Eye, EyeOff, Lock, Mail } from "lucide-react";

import OpenAIMark from "../components/OpenAIMark.jsx";
import { useAuth } from "../hooks/useAuth.jsx";
import { ROTATING } from "../lib/constants.js";

export default function Login() {
  const { signIn, expiredNotice } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rot, setRot] = useState(0);
  const [touched, setTouched] = useState(false);
  const [serverError, setServerError] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setRot((r) => (r + 1) % ROTATING.length), 2800);
    return () => clearInterval(t);
  }, []);

  const emailValid = /\S+@\S+\.\S+/.test(email);
  const canSubmit = emailValid && password.length > 0;

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    setTouched(true);
    setServerError(null);
    if (!canSubmit || loading) return;
    setLoading(true);
    try {
      await signIn(email, password);
      // On success the auth state flips and App swaps this view out.
    } catch (err) {
      setServerError(err.message);
      setLoading(false);
    }
  };

  const RotIcon = ROTATING[rot].icon;

  return (
    <div className="login-root">
      <aside className="login-hero">
        <div className="hero-noise" />
        <div className="hero-orbit orbit-1" />
        <div className="hero-orbit orbit-2" />
        <div className="hero-orbit orbit-3" />
        <div className="hero-top">
          <div className="brand-mark">
            <div className="brand-glyph"><span className="glyph-mk">MK</span></div>
            <span className="brand-name">Mail<b>Kit</b></span>
          </div>
          <div className="powered-lockup">
            <OpenAIMark size={15} color="#fff" />
            <span className="pl-openai">Powered by OpenAI</span>
          </div>
        </div>
        <div className="hero-mid">
          <p className="hero-eyebrow">Intelligent Email Assistant</p>
          <h1 className="hero-title">Your inbox,<br /><span className="hero-title-accent">handled by AI.</span></h1>
          <p className="hero-sub">Stop drowning in email. Summarise, sort, and reply - by chat or by voice - while you focus on the work that matters.</p>
          <div className="hero-rotator" key={rot}>
            <div className="rot-icon"><RotIcon size={16} strokeWidth={2.4} /></div>
            <span>{ROTATING[rot].text}</span>
          </div>
        </div>
        <div className="hero-foot">
          <div className="hero-stat"><b>120+</b><span>emails / day, sorted</span></div>
          <div className="hero-divider" />
          <div className="hero-stat"><b>28%</b><span>of the week, reclaimed</span></div>
        </div>
      </aside>

      <main className="login-panel">
        <form className="login-card" onSubmit={handleSubmit}>
          <div className="card-top-row">
            <div className="card-badge">Welcome</div>
            <div className="openai-chip"><OpenAIMark size={13} color="#1D4FD8" /> Powered by OpenAI</div>
          </div>
          <h2 className="card-title">Sign in to your inbox</h2>
          <p className="card-sub">Sign in with the account your team configured on the assistant.</p>

          {expiredNotice && (
            <div className="card-note" role="status" style={{ justifyContent: "flex-start", marginBottom: 14 }}>
              Your session ended. Please sign in again.
            </div>
          )}

          <label className={`field ${touched && !emailValid ? "field-error" : ""}`}>
            <span className="field-label">Email address</span>
            <div className="field-wrap">
              <Mail size={17} className="field-icon" />
              <input type="email" name="email" placeholder="you@monash.edu" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
            </div>
            {touched && !emailValid && <span className="field-hint">Enter an email like name@domain.com</span>}
          </label>

          <label className="field">
            <span className="field-label">Password</span>
            <div className="field-wrap">
              <Lock size={17} className="field-icon" />
              <input type={showPw ? "text" : "password"} name="password" placeholder="Your password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
              <button type="button" className="pw-toggle" onClick={() => setShowPw((s) => !s)} tabIndex={-1} aria-label="Toggle password">
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>

          {serverError && <span className="field-hint" role="alert" style={{ marginBottom: 10 }}>{serverError}</span>}

          <button type="submit" className={`login-btn ${loading ? "is-loading" : ""}`} disabled={loading || !canSubmit}>
            {loading ? <span className="spinner" /> : <>Log in <ArrowRight size={17} strokeWidth={2.6} /></>}
          </button>

          <div className="card-note"><span className="dot" />Credentials are verified by the assistant API. No email data loads until you sign in.</div>
        </form>
        <p className="panel-foot">FIT3164 · DS-25 · Intelligent Email Assistant</p>
      </main>
    </div>
  );
}
