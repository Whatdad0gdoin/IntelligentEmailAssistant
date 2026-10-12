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
 *
 * The same card also creates an account (POST /api/auth/signup), so a new user
 * needs nobody to set one up for them. A new account opens on the demo inbox;
 * the card says so, and that Gmail is connected afterwards from Settings, so
 * nobody is left wondering how their own email gets in.
 */

import { useEffect, useState } from "react";
import { ArrowRight, Eye, EyeOff, KeyRound, Lock, Mail } from "lucide-react";

import * as api from "../api/client.js";
import OpenAIMark from "../components/OpenAIMark.jsx";
import { useAuth } from "../hooks/useAuth.jsx";
import { ROTATING } from "../lib/constants.js";

// The backend's rule (MIN_PASSWORD in backend/routes/auth.py), checked here
// too so the button explains itself before a round trip does.
const MIN_PASSWORD = 8;

export default function Login() {
  const { signIn, signUp, expiredNotice } = useAuth();

  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  // From GET /api/auth/signup, fetched the first time the form switches to
  // sign-up: whether it is on, and whether it needs an invite code.
  const [signupOptions, setSignupOptions] = useState(null);
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rot, setRot] = useState(0);
  const [touched, setTouched] = useState(false);
  const [serverError, setServerError] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setRot((r) => (r + 1) % ROTATING.length), 2800);
    return () => clearInterval(t);
  }, []);

  const signingUp = mode === "signup";
  const codeRequired = Boolean(signupOptions?.invite_code_required);
  const signupOff = signingUp && signupOptions?.enabled === false;

  const emailValid = /\S+@\S+\.\S+/.test(email);
  const passwordLongEnough = password.length >= MIN_PASSWORD;
  const passwordsMatch = password === confirm;
  const canSubmit = signingUp
    ? !signupOff && emailValid && passwordLongEnough && passwordsMatch
      && (!codeRequired || inviteCode.trim().length > 0)
    : emailValid && password.length > 0;

  const switchMode = async (next) => {
    setMode(next);
    setTouched(false);
    setServerError(null);
    setConfirm("");
    if (next === "signup" && signupOptions === null) {
      try {
        setSignupOptions(await api.signupOptions());
      } catch {
        // Unknown is treated as "open, no code"; the server still decides,
        // and its answer to the submit says what is wrong.
        setSignupOptions({ enabled: true, invite_code_required: false });
      }
    }
  };

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    setTouched(true);
    setServerError(null);
    if (!canSubmit || loading) return;
    setLoading(true);
    try {
      if (signingUp) await signUp(email, password, inviteCode);
      else await signIn(email, password);
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
          {/* Measured, not marketing: eval/BENCHMARKS.md, headline figures
              (FR-02 run 13, strict, test split; NFR-01 cold load, median). */}
          <div className="hero-stat"><b>89.8%</b><span>of test emails sorted correctly</span></div>
          <div className="hero-divider" />
          <div className="hero-stat"><b>2.0 s</b><span>to sort a fresh inbox of 25</span></div>
        </div>
      </aside>

      <main className="login-panel">
        <form className="login-card" onSubmit={handleSubmit}>
          <div className="card-top-row">
            <div className="card-badge">{signingUp ? "New account" : "Welcome"}</div>
            <div className="openai-chip"><OpenAIMark size={13} color="#1D4FD8" /> Powered by OpenAI</div>
          </div>
          <h2 className="card-title">{signingUp ? "Create your account" : "Sign in to your inbox"}</h2>
          <p className="card-sub">
            {signingUp
              ? "You start on a demo inbox. Connect your Gmail from Settings to see your own email: read-only, and you can disconnect at any time."
              : "Sign in with your MailKit account."}
          </p>

          {expiredNotice && !signingUp && (
            <div className="card-note" role="status" style={{ justifyContent: "flex-start", marginBottom: 14 }}>
              Your session ended. Please sign in again.
            </div>
          )}

          {signupOff && (
            <span className="field-hint" role="alert" style={{ marginBottom: 14 }}>
              Sign-up is turned off on this server. Ask the team for an account.
            </span>
          )}

          <label className={`field ${touched && !emailValid ? "field-error" : ""}`}>
            <span className="field-label">Email address</span>
            <div className="field-wrap">
              <Mail size={17} className="field-icon" />
              <input type="email" name="email" placeholder="you@monash.edu" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete={signingUp ? "email" : "username"} />
            </div>
            {touched && !emailValid && <span className="field-hint">Enter an email like name@domain.com</span>}
          </label>

          <label className={`field ${signingUp && touched && !passwordLongEnough ? "field-error" : ""}`}>
            <span className="field-label">Password</span>
            <div className="field-wrap">
              <Lock size={17} className="field-icon" />
              <input type={showPw ? "text" : "password"} name="password"
                     placeholder={signingUp ? `At least ${MIN_PASSWORD} characters` : "Your password"}
                     value={password} onChange={(e) => setPassword(e.target.value)}
                     autoComplete={signingUp ? "new-password" : "current-password"} />
              <button type="button" className="pw-toggle" onClick={() => setShowPw((s) => !s)} tabIndex={-1} aria-label="Toggle password">
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {signingUp && touched && !passwordLongEnough && (
              <span className="field-hint">Use at least {MIN_PASSWORD} characters</span>
            )}
          </label>

          {signingUp && (
            <label className={`field ${confirm && !passwordsMatch ? "field-error" : ""}`}>
              <span className="field-label">Confirm password</span>
              <div className="field-wrap">
                <Lock size={17} className="field-icon" />
                <input type={showPw ? "text" : "password"} name="confirm" placeholder="Type it again"
                       value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
              </div>
              {confirm && !passwordsMatch && <span className="field-hint">The passwords do not match</span>}
            </label>
          )}

          {signingUp && codeRequired && (
            <label className="field">
              <span className="field-label">Invite code</span>
              <div className="field-wrap">
                <KeyRound size={17} className="field-icon" />
                <input type="text" name="invite_code" placeholder="From the team" value={inviteCode}
                       onChange={(e) => setInviteCode(e.target.value)} autoComplete="off" />
              </div>
            </label>
          )}

          {serverError && <span className="field-hint" role="alert" style={{ marginBottom: 10 }}>{serverError}</span>}

          <button type="submit" className={`login-btn ${loading ? "is-loading" : ""}`} disabled={loading || !canSubmit}>
            {loading
              ? <span className="spinner" />
              : <>{signingUp ? "Create account" : "Log in"} <ArrowRight size={17} strokeWidth={2.6} /></>}
          </button>

          <p className="card-switch-row">
            {signingUp ? "Already have an account?" : "New to MailKit?"}{" "}
            <button type="button" className="card-switch" onClick={() => switchMode(signingUp ? "signin" : "signup")}>
              {signingUp ? "Sign in" : "Create an account"}
            </button>
          </p>

          <div className="card-note">
            <span className="dot" />
            {signingUp
              ? "Your password is stored only as a one-way hash. MailKit never sends email."
              : "Credentials are verified by the assistant API. No email data loads until you sign in."}
          </div>
        </form>
        <p className="panel-foot">FIT3164 · DS-25 · Intelligent Email Assistant</p>
      </main>
    </div>
  );
}
