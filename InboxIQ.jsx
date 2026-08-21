import { useState, useEffect } from "react";
import {
  Mail, Lock, ArrowRight, Sparkles, Mic, Languages, ListChecks, Eye, EyeOff,
  MessageSquareReply, Volume2, SlidersHorizontal, Inbox, Settings, LogOut,
  Search, Star, Paperclip, ChevronRight, Hammer, Bell, PenLine
} from "lucide-react";

/* OpenAI blossom mark (generic geometric mark, not the trademarked wordmark) */
function OpenAIMark({ size = 20, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="OpenAI">
      <path d="M21.3 9.9a5.6 5.6 0 0 0-.5-4.6 5.7 5.7 0 0 0-6.1-2.7A5.6 5.6 0 0 0 10.4 0 5.7 5.7 0 0 0 5 3.9a5.6 5.6 0 0 0-3.8 2.7 5.7 5.7 0 0 0 .7 6.7 5.6 5.6 0 0 0 .5 4.6 5.7 5.7 0 0 0 6.1 2.7A5.6 5.6 0 0 0 13.6 24a5.7 5.7 0 0 0 5.4-3.9 5.6 5.6 0 0 0 3.8-2.7 5.7 5.7 0 0 0-.7-6.7l1.2-.8ZM13.6 22.4a4.2 4.2 0 0 1-2.7-1l.1-.1 4.5-2.6a.7.7 0 0 0 .4-.6v-6.4l1.9 1.1v5.3a4.2 4.2 0 0 1-4.2 4.3ZM4.5 18.5a4.2 4.2 0 0 1-.5-2.8v-.2l4.5 2.6a.7.7 0 0 0 .7 0l5.5-3.2v2.2l-4.6 2.7a4.2 4.2 0 0 1-5.7-1.5v.2Zm-1.2-9.7a4.2 4.2 0 0 1 2.2-1.8v5.4a.7.7 0 0 0 .4.6l5.5 3.2-1.9 1.1-4.6-2.6a4.2 4.2 0 0 1-1.6-5.7v.2Zm15.6 3.6-5.5-3.2 1.9-1.1 4.6 2.6a4.2 4.2 0 0 1-.7 7.6v-5.4a.7.7 0 0 0-.4-.6l.6.5Zm1.9-2.8-.1-.1-4.5-2.6a.7.7 0 0 0-.7 0L11 12.3v-2.2l4.6-2.7a4.2 4.2 0 0 1 6.2 4.3v.2Zm-11.9 3.9-1.9-1.1V7.1a4.2 4.2 0 0 1 6.9-3.2l-.1.1L8.3 6.5a.7.7 0 0 0-.4.6l.3 6.4ZM9.9 12 12.4 10.5l2.5 1.5v2.9L12.4 16.4 9.9 14.9V12Z" fill={color}/>
    </svg>
  );
}

/* ============================ DATA ============================ */
const ROTATING = [
  { icon: Sparkles, text: "Summarise unread emails in seconds" },
  { icon: ListChecks, text: "Auto-sort your inbox into smart categories" },
  { icon: Mic, text: "Control your inbox with your voice" },
  { icon: Languages, text: "Reply in any language, any tone" },
];

const FEATURES = [
  { id: "inbox", label: "Inbox", icon: Inbox, group: "main" },
  { id: "summarise", label: "Summarise", icon: Sparkles, group: "ai", desc: "Condense unread emails into a 2–3 sentence brief." },
  { id: "categorise", label: "Auto-Categorise", icon: ListChecks, group: "ai", desc: "Sort every email into Work, Personal, Promotions & Studies." },
  { id: "reply", label: "Draft Reply", icon: MessageSquareReply, group: "ai", desc: "Generate a reply you review and approve before sending." },
  { id: "tone", label: "Tone & Translate", icon: SlidersHorizontal, group: "ai", desc: "Rewrite replies in any tone, or translate to any language." },
  { id: "speak", label: "Read Aloud", icon: Volume2, group: "voice", desc: "Listen to summaries with built-in text-to-speech." },
  { id: "voice", label: "Voice Commands", icon: Mic, group: "voice", desc: "Control your inbox hands-free with your voice." },
];

const CATEGORIES = [
  { key: "work", label: "Work", color: "#2563EB" },
  { key: "personal", label: "Personal", color: "#0891B2" },
  { key: "promo", label: "Promotions", color: "#D97706" },
  { key: "studies", label: "Studies", color: "#059669" },
];

const EMAILS = [
  { id: 1, from: "Mr Robinson", email: "d.robinson@northgate.com.au", initials: "MR", subject: "Project deadline moved to Friday", preview: "Hi, can we reschedule our Thursday meeting to Friday at 2pm? I'd like to review the report together before…", cat: "work", time: "9:24 AM", unread: true, star: true, attach: true,
    body: "Hi,\n\nCan we reschedule our Thursday meeting to Friday at 2pm? I'd like to review the quarterly report together before it goes out to the wider team.\n\nI've attached the latest draft so you can take a look beforehand. Let me know if that time works for you.\n\nBest regards,\nDavid Robinson\nOperations Manager, Northgate" },
  { id: 2, from: "Monash Enrolments", email: "no-reply@monash.edu", initials: "ME", subject: "Semester 2 unit registration now open", preview: "Your registration window for Semester 2 has opened. Please complete your enrolment by the census date to…", cat: "studies", time: "8:10 AM", unread: true, star: false, attach: false,
    body: "Dear Student,\n\nYour registration window for Semester 2 has now opened. Please complete your enrolment by the census date to avoid late fees.\n\nYou can register for units through the student portal. If you have any questions about your course plan, please contact your faculty advisor.\n\nKind regards,\nMonash Enrolments Team" },
  { id: 3, from: "Sarah Chen", email: "sarah.chen.mel@gmail.com", initials: "SC", subject: "Dinner this weekend?", preview: "Hey! A few of us are getting together Saturday night. Would love for you to come along - let me know if…", cat: "personal", time: "Yesterday", unread: false, star: false, attach: false,
    body: "Hey!\n\nA few of us are getting together Saturday night for dinner at that new ramen place in the city. Would love for you to come along!\n\nWe're thinking around 7pm. Let me know if you can make it and I'll add you to the booking.\n\nTalk soon,\nSarah" },
  { id: 4, from: "TechDeals", email: "offers@techdeals-mail.com", initials: "TD", subject: "⚡ 48-hour flash sale - up to 60% off", preview: "Our biggest sale of the season is here. Grab premium gear at unbeatable prices before the clock runs out…", cat: "promo", time: "Yesterday", unread: true, star: false, attach: false,
    body: "Our biggest sale of the season is here!\n\nGrab premium gear at unbeatable prices before the clock runs out. Up to 60% off laptops, headphones, and accessories.\n\nThis offer ends in 48 hours. Shop now and don't miss out.\n\nUnsubscribe | Manage preferences" },
  { id: 5, from: "Dr Amelia Ford", email: "a.ford@monash.edu", initials: "AF", subject: "Feedback on your research proposal", preview: "I've reviewed your draft and left comments throughout. Overall a strong direction - a few points on the…", cat: "studies", time: "Mon", unread: false, star: true, attach: true,
    body: "Hi,\n\nI've reviewed your draft and left comments throughout the document. Overall it's a strong direction and I can see the project taking shape well.\n\nA few points on the methodology section need tightening, particularly around your evaluation metrics. Let's discuss these at our next supervision meeting.\n\nBest,\nDr Amelia Ford" },
  { id: 6, from: "GitHub", email: "noreply@github.com", initials: "GH", subject: "Security alert on ds-25/email-assistant", preview: "We detected a new sign-in to your account from a new device. If this was you, no action is needed…", cat: "work", time: "Mon", unread: false, star: false, attach: false,
    body: "Hi there,\n\nWe detected a new sign-in to your account from a new device. If this was you, no action is needed.\n\nIf you don't recognise this activity, please secure your account by changing your password immediately.\n\nThanks,\nThe GitHub Team" },
];

/* ============================ STYLES ============================ */
const CSS = `
:root {
  --ink:#1A2233;--ink-2:#2B3648;--ink-3:#3D4A5C;--paper:#F7F9FC;--paper-2:#EDF1F7;--white:#FFFFFF;
  --blue:#2563EB;--blue-deep:#1D4FD8;--blue-dark:#1E3A8A;--blue-glow:#60A5FA;--blue-wash:#EFF4FF;
  --amber:#D97706;--coral:#DC2626;--violet:#7C3AED;--green:#16A34A;
  --grey:#64748B;--grey-2:#94A3B8;--line:#E2E8F0;--line-2:#EDF1F7;
  --shadow-md:0 4px 16px rgba(30,58,138,0.07),0 2px 6px rgba(30,58,138,0.04);
  --shadow-lg:0 18px 50px rgba(30,41,59,0.14),0 6px 18px rgba(30,41,59,0.08);
  --shadow-blue:0 6px 20px rgba(37,99,235,0.22);
  --r-sm:6px;--r-md:10px;--r-lg:14px;--r-xl:20px;
  --font-display:'Plus Jakarta Sans',system-ui,sans-serif;--font-body:'Inter',system-ui,sans-serif;
}
.iq * { margin:0; padding:0; box-sizing:border-box; }
.iq { font-family:var(--font-body); color:var(--ink); height:100%; -webkit-font-smoothing:antialiased; }
.iq button { font-family:inherit; cursor:pointer; border:none; background:transparent; }
.iq button.login-btn, .iq button.compose-btn { background:linear-gradient(135deg,var(--blue),var(--blue-deep)); }
.iq input { font-family:inherit; }
.iq ::selection { background:var(--blue); color:#fff; }

/* LOGIN */
.login-root { display:grid; grid-template-columns:1.05fr 1fr; height:100%; overflow:hidden; }
.login-hero { position:relative; background:linear-gradient(160deg,#1E3A8A 0%,#1E40AF 50%,#1D4ED8 100%); color:#fff; padding:44px 52px; display:flex; flex-direction:column; justify-content:space-between; overflow:hidden; }
.hero-noise { position:absolute; inset:0; background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,0.05) 1px,transparent 0); background-size:22px 22px; pointer-events:none; }
.hero-orbit { position:absolute; border-radius:50%; border:1px solid rgba(96,165,250,0.16); pointer-events:none; }
.orbit-1 { width:480px; height:480px; right:-180px; top:-120px; animation:float 18s ease-in-out infinite; }
.orbit-2 { width:320px; height:320px; right:-60px; top:40px; border-color:rgba(96,165,250,0.24); animation:float 14s ease-in-out infinite reverse; }
.orbit-3 { width:200px; height:200px; left:-80px; bottom:80px; border-color:rgba(96,165,250,0.18); animation:float 20s ease-in-out infinite; }
@keyframes float { 0%,100%{transform:translate(0,0);} 50%{transform:translate(-14px,18px);} }
.hero-top { position:relative; z-index:2; }
.brand-mark { display:flex; align-items:center; gap:11px; }
.brand-glyph { width:38px; height:38px; border-radius:11px; background:linear-gradient(135deg,var(--blue),var(--blue-deep)); display:grid; place-items:center; color:#fff; box-shadow:var(--shadow-blue); }
.glyph-mk { font-family:var(--font-display); font-weight:700; font-size:16px; letter-spacing:-0.02em; color:#fff; }
.glyph-mk.sm { font-size:14px; }
.brand-name { font-family:var(--font-display); font-size:20px; font-weight:500; letter-spacing:-0.02em; }
.brand-name b { font-weight:700; color:var(--blue-glow); }
.hero-mid { position:relative; z-index:2; max-width:460px; }
.hero-eyebrow { font-size:12px; font-weight:600; letter-spacing:0.14em; text-transform:uppercase; color:var(--blue-glow); margin-bottom:18px; }
.hero-title { font-family:var(--font-display); font-size:clamp(38px,4.4vw,58px); font-weight:700; line-height:1.02; letter-spacing:-0.03em; margin-bottom:22px; }
.hero-title-accent { background:linear-gradient(100deg,var(--blue-glow),var(--blue)); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
.hero-sub { font-size:16px; line-height:1.62; color:rgba(255,255,255,0.72); margin-bottom:34px; max-width:400px; }
.hero-rotator { display:inline-flex; align-items:center; gap:12px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.10); padding:12px 18px 12px 12px; border-radius:40px; font-size:14.5px; font-weight:450; color:rgba(255,255,255,0.92); animation:rotIn 0.5s cubic-bezier(0.22,1,0.36,1); }
@keyframes rotIn { from{opacity:0;transform:translateY(8px);} to{opacity:1;transform:translateY(0);} }
.rot-icon { width:30px; height:30px; border-radius:9px; flex-shrink:0; background:linear-gradient(135deg,var(--blue),var(--blue-deep)); display:grid; place-items:center; color:#fff; }
.hero-foot { position:relative; z-index:2; display:flex; align-items:center; gap:26px; }
.hero-stat { display:flex; flex-direction:column; gap:3px; }
.hero-stat b { font-family:var(--font-display); font-size:26px; font-weight:700; letter-spacing:-0.02em; }
.hero-stat span { font-size:12.5px; color:rgba(255,255,255,0.55); }
.hero-divider { width:1px; height:38px; background:rgba(255,255,255,0.14); }
.login-panel { background:var(--paper); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:44px; position:relative; }
.login-card { width:100%; max-width:400px; background:#fff; border:1px solid var(--line-2); border-radius:var(--r-xl); padding:40px 38px 30px; box-shadow:var(--shadow-lg); animation:cardUp 0.6s cubic-bezier(0.22,1,0.36,1); }
@keyframes cardUp { from{opacity:0;transform:translateY(20px) scale(0.98);} to{opacity:1;transform:translateY(0) scale(1);} }
.card-badge { display:inline-block; background:var(--blue-wash); color:var(--blue-deep); font-size:11.5px; font-weight:600; letter-spacing:0.05em; padding:5px 13px; border-radius:30px; }
.card-title { font-family:var(--font-display); font-size:25px; font-weight:600; letter-spacing:-0.02em; color:var(--ink); margin-bottom:8px; }
.card-sub { font-size:13.5px; line-height:1.55; color:var(--grey); margin-bottom:26px; }
.field { display:block; margin-bottom:18px; }
.field-label { display:block; font-size:12.5px; font-weight:600; color:var(--ink-3); margin-bottom:8px; }
.field-wrap { display:flex; align-items:center; gap:10px; background:var(--paper); border:1.6px solid var(--line); border-radius:var(--r-md); padding:0 14px; transition:border-color 0.18s,box-shadow 0.18s,background 0.18s; }
.field-wrap:focus-within { border-color:var(--blue); background:#fff; box-shadow:0 0 0 4px rgba(37,99,235,0.12); }
.field-icon { color:var(--grey-2); flex-shrink:0; }
.field-wrap:focus-within .field-icon { color:var(--blue-deep); }
.field-wrap input { flex:1; border:none; outline:none; background:transparent; padding:13px 0; font-size:15px; color:var(--ink); }
.field-wrap input::placeholder { color:var(--grey-2); }
.pw-toggle { display:grid; place-items:center; color:var(--grey-2); padding:4px; }
.pw-toggle:hover { color:var(--ink-3); }
.field-error .field-wrap { border-color:var(--coral); }
.field-hint { display:block; font-size:12px; color:var(--coral); margin-top:7px; }
.login-btn { width:100%; margin-top:8px; display:flex; align-items:center; justify-content:center; gap:9px; background:linear-gradient(135deg,var(--blue),var(--blue-deep)); color:#fff; font-size:15.5px; font-weight:600; padding:15px; border-radius:var(--r-md); box-shadow:var(--shadow-blue); transition:transform 0.16s,box-shadow 0.16s,filter 0.16s; }
.login-btn:hover:not(:disabled) { transform:translateY(-2px); box-shadow:0 12px 34px rgba(37,99,235,0.30); }
.login-btn:active:not(:disabled) { transform:translateY(0); }
.login-btn:disabled { cursor:not-allowed; background:linear-gradient(135deg,#94A3B8,#7C8BA0); box-shadow:none; opacity:0.85; }
.login-btn.is-loading { filter:none; opacity:0.92; }
.spinner { width:19px; height:19px; border-radius:50%; border:2.4px solid rgba(255,255,255,0.35); border-top-color:#fff; animation:spin 0.7s linear infinite; }
@keyframes spin { to{transform:rotate(360deg);} }
.card-note { display:flex; align-items:center; gap:8px; margin-top:22px; font-size:12px; color:var(--grey); justify-content:center; }
.card-note .dot { width:7px; height:7px; border-radius:50%; background:var(--green); box-shadow:0 0 0 3px rgba(35,178,109,0.16); animation:pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
.panel-foot { position:absolute; bottom:28px; font-size:12px; color:var(--grey-2); letter-spacing:0.02em; }

/* DASHBOARD */
.dash-root { display:grid; grid-template-columns:264px 1fr; height:100%; background:var(--paper); overflow:hidden; }
.sidebar { background:linear-gradient(180deg,#1E293B 0%,#172033 100%); color:#fff; display:flex; flex-direction:column; padding:22px 16px 16px; position:relative; }
.side-brand { display:flex; align-items:center; gap:10px; padding:0 8px 20px; }
.brand-glyph.sm { width:34px; height:34px; border-radius:10px; background:linear-gradient(135deg,var(--blue),var(--blue-deep)); box-shadow:var(--shadow-blue); color:#fff; display:grid; place-items:center; }
.brand-name.sm { font-family:var(--font-display); font-size:18px; font-weight:500; letter-spacing:-0.02em; }
.brand-name.sm b { font-weight:700; color:var(--blue-glow); }
.compose-btn { display:flex; align-items:center; justify-content:center; gap:8px; background:linear-gradient(135deg,var(--blue),var(--blue-deep)); color:#fff; font-size:14px; font-weight:600; padding:12px; border-radius:var(--r-md); margin-bottom:18px; box-shadow:var(--shadow-blue); transition:transform 0.16s,box-shadow 0.16s; }
.compose-btn:hover { transform:translateY(-1px); box-shadow:0 10px 28px rgba(37,99,235,0.34); }
.side-nav { flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:2px; }
.side-nav::-webkit-scrollbar { width:0; }
.nav-group-label { font-size:10.5px; font-weight:600; letter-spacing:0.12em; text-transform:uppercase; color:rgba(255,255,255,0.34); padding:16px 12px 7px; }
.nav-item { display:flex; align-items:center; gap:12px; padding:10px 12px; border-radius:var(--r-md); color:rgba(255,255,255,0.72); font-size:14px; font-weight:450; width:100%; text-align:left; position:relative; transition:background 0.15s,color 0.15s; }
.nav-item:hover { background:rgba(255,255,255,0.06); color:#fff; }
.nav-item.active { background:rgba(96,165,250,0.16); color:#fff; }
.nav-item.active::before { content:""; position:absolute; left:0; top:50%; transform:translateY(-50%); width:3px; height:20px; border-radius:3px; background:var(--blue-glow); }
.nav-icon { display:grid; place-items:center; flex-shrink:0; }
.nav-item.active .nav-icon { color:var(--blue-glow); }
.nav-label { flex:1; }
.nav-badge { background:var(--blue); color:#fff; font-size:11px; font-weight:600; min-width:20px; height:20px; border-radius:20px; display:grid; place-items:center; padding:0 6px; }
.nav-soon { font-size:9.5px; font-weight:600; letter-spacing:0.05em; text-transform:uppercase; color:var(--amber); background:rgba(240,168,30,0.14); padding:3px 7px; border-radius:20px; }
.side-foot { margin-top:12px; border-top:1px solid rgba(255,255,255,0.08); padding-top:12px; }
.side-mini { display:flex; align-items:center; gap:12px; width:100%; padding:10px 12px; border-radius:var(--r-md); color:rgba(255,255,255,0.62); font-size:14px; transition:background 0.15s,color 0.15s; }
.side-mini:hover { background:rgba(255,255,255,0.06); color:#fff; }
.side-user { display:flex; align-items:center; gap:10px; margin-top:6px; padding:8px; border-radius:var(--r-md); background:rgba(255,255,255,0.04); }
.user-avatar { width:34px; height:34px; border-radius:9px; flex-shrink:0; background:linear-gradient(135deg,#475569,#334155); display:grid; place-items:center; font-weight:600; font-size:15px; }
.user-meta { flex:1; min-width:0; display:flex; flex-direction:column; }
.user-email { font-size:12.5px; font-weight:500; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:130px; }
.user-plan { font-size:10.5px; color:rgba(255,255,255,0.4); }
.logout-btn { color:rgba(255,255,255,0.5); padding:6px; border-radius:8px; flex-shrink:0; transition:background 0.15s,color 0.15s; }
.logout-btn:hover { background:rgba(220,38,38,0.10); color:var(--coral); }
.dash-main { overflow-y:auto; padding:26px 34px 40px; }
.main-head { display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:22px; }
.main-title { font-family:var(--font-display); font-size:28px; font-weight:600; letter-spacing:-0.02em; color:var(--ink); }
.main-sub { font-size:13.5px; color:var(--grey); margin-top:3px; }
.head-actions { display:flex; align-items:center; gap:10px; }
.search-box { display:flex; align-items:center; gap:9px; background:#fff; border:1.5px solid var(--line); border-radius:var(--r-md); padding:0 13px; width:260px; transition:border-color 0.16s,box-shadow 0.16s; }
.search-box:focus-within { border-color:var(--blue); box-shadow:0 0 0 4px rgba(37,99,235,0.10); }
.search-icon { color:var(--grey-2); flex-shrink:0; }
.search-box input { flex:1; border:none; outline:none; background:transparent; padding:11px 0; font-size:14px; color:var(--ink); }
.icon-btn { width:42px; height:42px; border-radius:var(--r-md); background:#fff; border:1.5px solid var(--line); display:grid; place-items:center; color:var(--grey); transition:color 0.15s,border-color 0.15s; }
.icon-btn:hover { color:var(--blue-deep); border-color:var(--blue); }
.filter-row { display:flex; gap:9px; margin-bottom:20px; flex-wrap:wrap; }
.chip { display:inline-flex; align-items:center; gap:8px; background:#fff; border:1.5px solid var(--line); padding:8px 14px; border-radius:30px; font-size:13px; font-weight:500; color:var(--grey); transition:all 0.16s; }
.chip:hover { border-color:var(--grey-2); color:var(--ink); }
.chip.on { background:var(--ink); border-color:var(--ink); color:#fff; }
.chip-dot { width:8px; height:8px; border-radius:50%; background:var(--chip,var(--grey)); }
.chip-count { font-size:11px; font-weight:600; background:var(--paper-2); color:var(--grey); padding:2px 7px; border-radius:20px; }
.chip.on .chip-count { background:rgba(255,255,255,0.18); color:#fff; }
.mail-list { display:flex; flex-direction:column; gap:8px; }
.mail-row { display:flex; align-items:flex-start; gap:14px; background:#fff; border:1.5px solid var(--line-2); border-radius:var(--r-lg); padding:15px 18px; text-align:left; position:relative; transition:transform 0.15s,box-shadow 0.15s,border-color 0.15s; animation:rowIn 0.4s cubic-bezier(0.22,1,0.36,1) backwards; width:100%; }
@keyframes rowIn { from{opacity:0;transform:translateY(10px);} to{opacity:1;transform:translateY(0);} }
.mail-row:hover { transform:translateY(-2px); box-shadow:var(--shadow-md); border-color:var(--line); }
.mail-row.sel { border-color:var(--blue); box-shadow:0 0 0 4px rgba(37,99,235,0.10); }
.mail-row.unread .mail-from { font-weight:600; color:var(--ink); }
.mail-row.unread .mail-subject { font-weight:600; }
.mail-avatar { width:42px; height:42px; border-radius:12px; flex-shrink:0; display:grid; place-items:center; color:#fff; font-size:14px; font-weight:600; letter-spacing:-0.01em; }
.mail-body { flex:1; min-width:0; }
.mail-line1 { display:flex; align-items:center; justify-content:space-between; margin-bottom:2px; }
.mail-from { font-size:14.5px; font-weight:500; color:var(--ink-2); }
.mail-time { font-size:12px; color:var(--grey-2); flex-shrink:0; margin-left:10px; }
.mail-line2 { display:flex; align-items:center; gap:8px; margin-bottom:4px; }
.mail-subject { font-size:13.5px; font-weight:450; color:var(--ink-3); display:flex; align-items:center; gap:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ic-star { flex-shrink:0; }
.ic-attach { color:var(--grey-2); flex-shrink:0; }
.mail-preview { font-size:13px; line-height:1.5; color:var(--grey); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.unread-dot { position:absolute; top:18px; right:18px; width:9px; height:9px; border-radius:50%; background:var(--blue); box-shadow:0 0 0 3px rgba(37,99,235,0.16); }
.mail-expand { display:flex; align-items:center; gap:14px; margin-top:12px; padding-top:12px; border-top:1px dashed var(--line); animation:expandIn 0.3s ease; }
@keyframes expandIn { from{opacity:0;} to{opacity:1;} }
.cat-tag { display:inline-flex; align-items:center; gap:7px; font-size:12px; font-weight:600; color:var(--c); background:color-mix(in srgb,var(--c) 12%,transparent); padding:5px 11px; border-radius:20px; }
.cat-dot { width:7px; height:7px; border-radius:50%; background:var(--c); }
.expand-hint { font-size:12px; color:var(--grey-2); font-style:italic; }
.soon-wrap { max-width:640px; margin:0 auto; padding-top:10px; }
.soon-crumb { display:flex; align-items:center; gap:8px; font-size:13px; color:var(--grey); margin-bottom:40px; }
.soon-crumb button { color:var(--blue-deep); font-weight:500; font-size:13px; }
.soon-crumb button:hover { text-decoration:underline; }
.soon-card { position:relative; overflow:hidden; background:#fff; border:1.5px solid var(--line-2); border-radius:var(--r-xl); padding:52px 44px 40px; text-align:center; box-shadow:var(--shadow-lg); animation:cardUp 0.5s cubic-bezier(0.22,1,0.36,1); }
.soon-glow { position:absolute; top:-80px; left:50%; transform:translateX(-50%); width:300px; height:300px; border-radius:50%; background:radial-gradient(circle,rgba(37,99,235,0.14),transparent 68%); pointer-events:none; }
.soon-icon { width:82px; height:82px; border-radius:22px; margin:0 auto 22px; background:linear-gradient(135deg,var(--blue-wash),#D2F1F6); color:var(--blue-deep); display:grid; place-items:center; position:relative; box-shadow:inset 0 0 0 1px rgba(37,99,235,0.18); animation:iconFloat 3s ease-in-out infinite; }
@keyframes iconFloat { 0%,100%{transform:translateY(0);} 50%{transform:translateY(-7px);} }
.soon-tag { display:inline-flex; align-items:center; gap:6px; background:rgba(240,168,30,0.14); color:#9A6A00; font-size:11.5px; font-weight:600; letter-spacing:0.04em; padding:6px 13px; border-radius:30px; margin-bottom:16px; }
.soon-title { font-family:var(--font-display); font-size:30px; font-weight:600; letter-spacing:-0.02em; color:var(--ink); margin-bottom:10px; }
.soon-desc { font-size:15px; line-height:1.6; color:var(--grey); max-width:380px; margin:0 auto 30px; }
.soon-banner { position:relative; overflow:hidden; background:linear-gradient(135deg,var(--ink),var(--ink-2)); color:#fff; font-family:var(--font-display); font-size:17px; font-weight:600; letter-spacing:0.16em; padding:18px; border-radius:var(--r-md); margin-bottom:28px; }
.soon-banner-shine { position:absolute; top:0; left:-60%; width:45%; height:100%; background:linear-gradient(100deg,transparent,rgba(37,99,235,0.34),transparent); animation:shine 2.6s ease-in-out infinite; }
@keyframes shine { 0%{left:-60%;} 60%,100%{left:130%;} }
.soon-back { color:var(--blue-deep); font-size:14px; font-weight:600; padding:10px 20px; border-radius:var(--r-md); border:1.5px solid var(--line); transition:background 0.15s,border-color 0.15s; }
.soon-back:hover { background:var(--blue-wash); border-color:var(--blue); }
.soon-foot { text-align:center; font-size:12.5px; color:var(--grey-2); margin-top:22px; }



/* Powered-by OpenAI lockup (hero) */
.powered-lockup { display:inline-flex; align-items:center; gap:8px; margin-top:16px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.12); padding:7px 15px; border-radius:30px; }
.pl-openai { font-size:13px; font-weight:600; color:#fff; }

/* OpenAI chip (login card) */
.card-top-row { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
.openai-chip { display:inline-flex; align-items:center; gap:6px; background:var(--blue-wash); color:var(--blue-deep); font-size:11.5px; font-weight:600; padding:5px 11px; border-radius:30px; border:1px solid #DCE6FB; }

/* ===== SPLIT INBOX (list + reader) ===== */
.inbox-split { display:grid; grid-template-columns:400px 1fr; gap:20px; height:100%; }
.inbox-left { display:flex; flex-direction:column; min-width:0; overflow:hidden; }
.inbox-left .mail-list { overflow-y:auto; padding-right:4px; flex:1; }
.inbox-left .main-head { margin-bottom:16px; }
.search-box.wide { width:100%; margin-bottom:16px; }
.inbox-right { min-width:0; }

/* Reader empty state */
.reader-empty { height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; background:#fff; border:1.5px solid var(--line-2); border-radius:var(--r-xl); padding:40px; }
.reader-empty-icon { width:80px; height:80px; border-radius:22px; background:var(--paper-2); color:var(--grey-2); display:grid; place-items:center; margin-bottom:20px; }
.reader-empty h3 { font-family:var(--font-display); font-size:19px; font-weight:600; color:var(--ink-2); margin-bottom:8px; }
.reader-empty p { font-size:14px; color:var(--grey); max-width:280px; line-height:1.55; }

/* Reader */
.reader { height:100%; display:flex; flex-direction:column; background:#fff; border:1.5px solid var(--line-2); border-radius:var(--r-xl); overflow:hidden; box-shadow:var(--shadow-md); animation:cardUp 0.4s cubic-bezier(0.22,1,0.36,1); }
.reader-toolbar { display:flex; align-items:center; gap:14px; padding:14px 20px; border-bottom:1px solid var(--line-2); background:var(--blue-wash); flex-wrap:wrap; }
.reader-toolbar-label { display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600; color:var(--blue-deep); text-transform:uppercase; letter-spacing:0.04em; flex-shrink:0; }
.reader-actions { display:flex; gap:8px; flex-wrap:wrap; }
.action-btn { display:inline-flex; align-items:center; gap:7px; background:#fff; border:1.5px solid var(--line); color:var(--ink-2); font-size:13px; font-weight:500; padding:8px 13px; border-radius:20px; transition:all 0.15s; }
.action-btn:hover { border-color:var(--blue); color:var(--blue-deep); background:#fff; transform:translateY(-1px); box-shadow:0 3px 10px rgba(37,99,235,0.12); }
.action-btn:active { transform:translateY(0); }

.reader-head { padding:22px 24px 18px; border-bottom:1px solid var(--line-2); }
.reader-subject { font-family:var(--font-display); font-size:21px; font-weight:600; letter-spacing:-0.01em; color:var(--ink); margin-bottom:16px; line-height:1.3; }
.reader-meta { display:flex; align-items:center; gap:13px; }
.mail-avatar.lg { width:46px; height:46px; border-radius:13px; font-size:15px; }
.reader-sender { flex:1; min-width:0; display:flex; flex-direction:column; }
.reader-from { font-size:15px; font-weight:600; color:var(--ink); }
.reader-addr { font-size:13px; color:var(--grey); }
.reader-right { display:flex; flex-direction:column; align-items:flex-end; gap:6px; }
.reader-time { font-size:12.5px; color:var(--grey-2); }

.reader-body { flex:1; overflow-y:auto; padding:24px; font-size:14.5px; line-height:1.7; color:var(--ink-3); }
.reader-body p { margin-bottom:2px; }
.reader-attach { display:inline-flex; align-items:center; gap:9px; margin-top:22px; padding:11px 15px; background:var(--paper); border:1px solid var(--line); border-radius:var(--r-md); font-size:13px; color:var(--grey); }
.attach-chip { background:#fff; border:1px solid var(--line); padding:4px 10px; border-radius:6px; font-weight:500; color:var(--ink-3); font-size:12.5px; }

.reader-foot { display:flex; gap:10px; padding:16px 24px; border-top:1px solid var(--line-2); background:var(--paper); }
.reply-btn { display:inline-flex; align-items:center; gap:8px; background:linear-gradient(135deg,var(--blue),var(--blue-deep)); color:#fff; font-size:14px; font-weight:600; padding:11px 20px; border-radius:var(--r-md); box-shadow:var(--shadow-blue); transition:transform 0.15s,box-shadow 0.15s; }
.reply-btn:hover { transform:translateY(-1px); box-shadow:0 8px 22px rgba(37,99,235,0.3); }
.reply-btn.ghost { background:#fff; color:var(--ink-2); border:1.5px solid var(--line); box-shadow:none; }
.reply-btn.ghost:hover { border-color:var(--blue); color:var(--blue-deep); box-shadow:0 3px 10px rgba(37,99,235,0.1); }
.iq button.reply-btn { background:linear-gradient(135deg,var(--blue),var(--blue-deep)); }
.iq button.reply-btn.ghost { background:#fff; }

/* Toast */
.toast { position:fixed; bottom:26px; right:26px; z-index:100; display:flex; align-items:center; gap:13px; background:var(--ink); color:#fff; padding:14px 20px 14px 16px; border-radius:var(--r-lg); box-shadow:var(--shadow-lg); max-width:340px; animation:toastIn 0.35s cubic-bezier(0.22,1,0.36,1); }
@keyframes toastIn { from{opacity:0;transform:translateY(16px) scale(0.96);} to{opacity:1;transform:translateY(0) scale(1);} }
.toast-icon { width:34px; height:34px; border-radius:10px; background:rgba(96,165,250,0.2); color:var(--blue-glow); display:grid; place-items:center; flex-shrink:0; }
.toast-text { display:flex; flex-direction:column; gap:2px; }
.toast-text b { font-size:14px; font-weight:600; }
.toast-text span { font-size:12.5px; color:rgba(255,255,255,0.7); line-height:1.4; }


@media (max-width:900px) { .login-root { grid-template-columns:1fr; } .login-hero { display:none; } .login-panel { padding:28px 20px; } }
@media (max-width:1080px) { .inbox-split { grid-template-columns:1fr; } .inbox-right { display:none; } .inbox-split.has-selection .inbox-left { display:none; } .inbox-split.has-selection .inbox-right { display:block; } }
@media (max-width:820px) { .dash-root { grid-template-columns:72px 1fr; } .brand-name.sm,.nav-label,.nav-soon,.compose-btn span,.user-meta,.side-mini span,.nav-group-label { display:none; } .compose-btn { padding:12px 0; } .side-user { justify-content:center; } .search-box { width:150px; } .dash-main { padding:20px 18px 32px; } }
`;

/* ============================ LOGIN ============================ */
function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rot, setRot] = useState(0);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setRot((r) => (r + 1) % ROTATING.length), 2800);
    return () => clearInterval(t);
  }, []);

  const emailValid = /\S+@\S+\.\S+/.test(email);
  const canSubmit = emailValid && password.length > 0;

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    setTouched(true);
    if (!canSubmit || loading) return;
    setLoading(true);
    setTimeout(() => onLogin(email), 900);
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
        <div className="login-card">
          <div className="card-top-row">
            <div className="card-badge">Welcome</div>
            <div className="openai-chip"><OpenAIMark size={13} color="#1D4FD8" /> Powered by OpenAI</div>
          </div>
          <h2 className="card-title">Sign in to your inbox</h2>
          <p className="card-sub">Enter any email domain and password to continue - this is a prototype.</p>

          <label className={`field ${touched && !emailValid ? "field-error" : ""}`}>
            <span className="field-label">Email domain</span>
            <div className="field-wrap">
              <Mail size={17} className="field-icon" />
              <input type="text" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(e); }} autoComplete="off" />
            </div>
            {touched && !emailValid && <span className="field-hint">Enter an email like name@domain.com</span>}
          </label>

          <label className="field">
            <span className="field-label">Password</span>
            <div className="field-wrap">
              <Lock size={17} className="field-icon" />
              <input type={showPw ? "text" : "password"} placeholder="Any password works" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(e); }} autoComplete="off" />
              <button type="button" className="pw-toggle" onClick={() => setShowPw((s) => !s)} tabIndex={-1} aria-label="Toggle password">
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>

          <button type="button" className={`login-btn ${loading ? "is-loading" : ""}`} disabled={loading} onClick={handleSubmit}>
            {loading ? <span className="spinner" /> : <>Log in <ArrowRight size={17} strokeWidth={2.6} /></>}
          </button>

          <div className="card-note"><span className="dot" />Prototype build - no real authentication. Any input is accepted.</div>
        </div>
        <p className="panel-foot">FIT3163 · DS-25 · Intelligent Email Assistant</p>
      </main>
    </div>
  );
}

/* ============================ DASHBOARD ============================ */
function SideItem({ f, active, onClick, soon, badge }) {
  const Icon = f.icon;
  const isActive = active === f.id;
  return (
    <button className={`nav-item ${isActive ? "active" : ""}`} onClick={() => onClick(f.id)}>
      <span className="nav-icon"><Icon size={18} strokeWidth={2.2} /></span>
      <span className="nav-label">{f.label}</span>
      {badge > 0 && <span className="nav-badge">{badge}</span>}
      {soon && <span className="nav-soon">soon</span>}
    </button>
  );
}

function InboxView({ filter, setFilter, shown, selected, setSelected, unreadCount, onAction }) {
  const openEmail = shown.find((e) => e.id === selected) || EMAILS.find((e) => e.id === selected);

  return (
    <div className="inbox-split">
      {/* LEFT: list */}
      <div className="inbox-left">
        <header className="main-head">
          <div>
            <h1 className="main-title">Inbox</h1>
            <p className="main-sub">{unreadCount} unread · {EMAILS.length} total</p>
          </div>
          <div className="head-actions">
            <button className="icon-btn" aria-label="Notifications"><Bell size={18} /></button>
          </div>
        </header>

        <div className="search-box wide">
          <Search size={16} className="search-icon" />
          <input placeholder="Search mail…" />
        </div>

        <div className="filter-row">
          <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
            All <span className="chip-count">{EMAILS.length}</span>
          </button>
          {CATEGORIES.map((c) => {
            const n = EMAILS.filter((e) => e.cat === c.key).length;
            return (
              <button key={c.key} className={`chip ${filter === c.key ? "on" : ""}`} onClick={() => setFilter(c.key)} style={{ "--chip": c.color }}>
                <span className="chip-dot" /> {c.label} <span className="chip-count">{n}</span>
              </button>
            );
          })}
        </div>

        <div className="mail-list">
          {shown.map((e, i) => {
            const cat = CATEGORIES.find((c) => c.key === e.cat);
            return (
              <button key={e.id} className={`mail-row ${e.unread ? "unread" : ""} ${selected === e.id ? "sel" : ""}`} style={{ animationDelay: `${i * 45}ms` }} onClick={() => setSelected(e.id)}>
                <span className="mail-avatar" style={{ background: cat.color }}>{e.initials}</span>
                <div className="mail-body">
                  <div className="mail-line1">
                    <span className="mail-from">{e.from}</span>
                    <span className="mail-time">{e.time}</span>
                  </div>
                  <div className="mail-line2">
                    <span className="mail-subject">
                      {e.star && <Star size={13} className="ic-star" fill="#D97706" stroke="#D97706" />}
                      {e.subject}
                    </span>
                    {e.attach && <Paperclip size={13} className="ic-attach" />}
                  </div>
                  <p className="mail-preview">{e.preview}</p>
                </div>
                {e.unread && <span className="unread-dot" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* RIGHT: reading pane */}
      <div className="inbox-right">
        {openEmail ? (
          <ReadingPane email={openEmail} onClose={() => setSelected(null)} onAction={onAction} />
        ) : (
          <div className="reader-empty">
            <div className="reader-empty-icon"><Inbox size={40} strokeWidth={1.6} /></div>
            <h3>Select an email to read</h3>
            <p>Choose a message from your inbox to view it here and try the AI tools.</p>
          </div>
        )}
      </div>
    </div>
  );
}

const MAIL_ACTIONS = [
  { id: "summarise", label: "Summarise", icon: Sparkles },
  { id: "speak", label: "Read Aloud", icon: Volume2 },
  { id: "reply", label: "Draft Reply", icon: MessageSquareReply },
  { id: "tone", label: "Tone & Translate", icon: SlidersHorizontal },
  { id: "voice", label: "Voice Reply", icon: Mic },
];

function ReadingPane({ email, onClose, onAction }) {
  const cat = CATEGORIES.find((c) => c.key === email.cat);
  return (
    <div className="reader" key={email.id}>
      {/* Action toolbar */}
      <div className="reader-toolbar">
        <span className="reader-toolbar-label">
          <Sparkles size={14} strokeWidth={2.2} /> AI tools
        </span>
        <div className="reader-actions">
          {MAIL_ACTIONS.map((a) => {
            const AI = a.icon;
            return (
              <button key={a.id} className="action-btn" onClick={() => onAction(a.label)}>
                <AI size={15} strokeWidth={2.2} />
                <span>{a.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Email header */}
      <div className="reader-head">
        <h2 className="reader-subject">{email.subject}</h2>
        <div className="reader-meta">
          <span className="mail-avatar lg" style={{ background: cat.color }}>{email.initials}</span>
          <div className="reader-sender">
            <span className="reader-from">{email.from}</span>
            <span className="reader-addr">{email.email}</span>
          </div>
          <div className="reader-right">
            <span className="cat-tag" style={{ "--c": cat.color }}><span className="cat-dot" /> {cat.label}</span>
            <span className="reader-time">{email.time}</span>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="reader-body">
        {email.body.split("\n").map((line, i) =>
          line.trim() === "" ? <br key={i} /> : <p key={i}>{line}</p>
        )}
        {email.attach && (
          <div className="reader-attach">
            <Paperclip size={15} /> <span>1 attachment</span>
            <span className="attach-chip">report-draft.pdf</span>
          </div>
        )}
      </div>

      {/* Footer reply bar (non-functional) */}
      <div className="reader-foot">
        <button className="reply-btn" onClick={() => onAction("Draft Reply")}>
          <MessageSquareReply size={16} strokeWidth={2.2} /> Reply
        </button>
        <button className="reply-btn ghost" onClick={() => onAction("Read Aloud")}>
          <Volume2 size={16} strokeWidth={2.2} /> Read Aloud
        </button>
      </div>
    </div>
  );
}

function ComingSoon({ feature, onBack }) {
  const Icon = feature.icon;
  return (
    <div className="soon-wrap">
      <div className="soon-crumb">
        <button onClick={onBack}>Inbox</button>
        <ChevronRight size={14} />
        <span>{feature.label}</span>
      </div>
      <div className="soon-card">
        <div className="soon-glow" />
        <div className="soon-icon"><Icon size={34} strokeWidth={2} /></div>
        <div className="soon-tag"><Hammer size={13} strokeWidth={2.4} /> In development</div>
        <h2 className="soon-title">{feature.label}</h2>
        <p className="soon-desc">{feature.desc}</p>
        <div className="soon-banner"><span className="soon-banner-shine" />TO BE ADDED SOON</div>
        <button className="soon-back" onClick={onBack}>← Back to inbox</button>
      </div>
      <p className="soon-foot">This feature is part of the Semester 2 build roadmap.</p>
    </div>
  );
}

function Dashboard({ user, onLogout }) {
  const [active, setActive] = useState("inbox");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [toast, setToast] = useState(null);

  const showToast = (label) => {
    setToast(label);
    clearTimeout(window.__iqToast);
    window.__iqToast = setTimeout(() => setToast(null), 2600);
  };

  const activeFeature = FEATURES.find((f) => f.id === active);
  const shown = filter === "all" ? EMAILS : EMAILS.filter((e) => e.cat === filter);
  const unreadCount = EMAILS.filter((e) => e.unread).length;

  return (
    <div className="dash-root">
      <aside className="sidebar">
        <div className="side-brand">
          <div className="brand-glyph sm"><span className="glyph-mk sm">MK</span></div>
          <span className="brand-name sm">Mail<b>Kit</b></span>
        </div>
        <button className="compose-btn"><PenLine size={16} strokeWidth={2.4} /> <span>Compose</span></button>
        <nav className="side-nav">
          <SideItem f={FEATURES[0]} active={active} onClick={setActive} badge={unreadCount} />
          <div className="nav-group-label">AI Tools</div>
          {FEATURES.filter((f) => f.group === "ai").map((f) => <SideItem key={f.id} f={f} active={active} onClick={setActive} soon />)}
          <div className="nav-group-label">Voice</div>
          {FEATURES.filter((f) => f.group === "voice").map((f) => <SideItem key={f.id} f={f} active={active} onClick={setActive} soon />)}
        </nav>
        <div className="side-foot">
          <button className="side-mini"><Settings size={17} /> <span>Settings</span></button>
          <div className="side-user">
            <div className="user-avatar">{user.email[0]?.toUpperCase()}</div>
            <div className="user-meta">
              <span className="user-email">{user.email}</span>
              <span className="user-plan">Prototype access</span>
            </div>
            <button className="logout-btn" onClick={onLogout} aria-label="Log out"><LogOut size={16} /></button>
          </div>
        </div>
      </aside>

      <main className="dash-main">
        {active === "inbox"
          ? <InboxView filter={filter} setFilter={setFilter} shown={shown} selected={selected} setSelected={setSelected} unreadCount={unreadCount} onAction={showToast} />
          : <ComingSoon feature={activeFeature} onBack={() => setActive("inbox")} />}
      </main>

      {toast && (
        <div className="toast" key={toast}>
          <span className="toast-icon"><Hammer size={15} strokeWidth={2.4} /></span>
          <div className="toast-text">
            <b>{toast}</b>
            <span>This feature is not functional yet - coming in Semester 2.</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================ ROOT ============================ */
export default function App() {
  const [user, setUser] = useState(null);
  return (
    <div className="iq" style={{ height: "100vh" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700&family=Inter:wght@400;450;500;600&display=swap');`}</style>
      <style>{CSS}</style>
      {user
        ? <Dashboard user={user} onLogout={() => setUser(null)} />
        : <LoginPage onLogin={(email) => setUser({ email })} />}
    </div>
  );
}
