/**
 * Static UI data, extracted verbatim from the original single-file InboxIQ.jsx.
 *
 * CATEGORIES holds the four classes the classifier may return. The fifth UI
 * bucket, "Review", is defined separately below: it is a destination for
 * unverified labels (spec section 4.3), never a value the model can produce.
 */

import { Inbox, Languages, ListChecks, Mic, Sparkles } from "lucide-react";

export const ROTATING = [
  { icon: Sparkles, text: "Summarise unread emails in seconds" },
  { icon: ListChecks, text: "Auto-sort your inbox into smart categories" },
  { icon: Mic, text: "Control your inbox with your voice" },
  { icon: Languages, text: "Reply in any language, any tone" },
];

/**
 * Nav features.
 *
 * `soon: true` marks a feature with no implementation behind it, and it is the
 * ONLY thing that puts the amber "soon" badge in the sidebar. It used to be a
 * literal prop passed to every AI and Voice item in Dashboard, which meant the
 * badge kept appearing on features whose endpoints had already shipped -- the
 * label described the state of the sidebar, not the state of the build.
 *
 * The rule now: a feature is `soon` when there is no route serving it.
 *   FR-01 summarise   -> POST /api/summarise    built
 *   FR-02 categorise  -> POST /api/classify     built
 *   FR-03 reply       -> POST /api/draft        built
 *   FR-05 voice       -> POST /api/voice/intent built
 *   speak             -> browser speechSynthesis, no backend needed
 *   FR-06/07 tone     -> nothing. Out of scope for this build, stays `soon`.
 */
// Sidebar destinations. Summarise, Read Aloud and Draft Reply are not here:
// they act on an open message and live on the reading pane. Tone is on the
// draft. Translation (FR-07) is out of scope.
export const FEATURES = [
  { id: "inbox", label: "Inbox", icon: Inbox, group: "main" },
  { id: "voice", label: "Voice Commands", icon: Mic, group: "voice", desc: "Control your inbox hands-free with your voice." },
];

export const CATEGORIES = [
  { key: "work", label: "Work", color: "#2563EB" },
  { key: "personal", label: "Personal", color: "#0891B2" },
  { key: "promo", label: "Promotions", color: "#D97706" },
  { key: "studies", label: "Studies", color: "#059669" },
];

/**
 * The fifth bucket (spec section 4.3). Kept separate from CATEGORIES above so
 * the four real classes stay exactly as the classifier's enum defines them:
 * "Review" is a UI destination, never a label the model can return.
 */
export const REVIEW_CATEGORY = {
  key: "review",
  label: "Review",
  color: "#64748B",
  explanation: "Low confidence, unverified label",
};


/** Maps an API category value onto the UI category key. */
export const API_TO_KEY = {
  Work: "work",
  Personal: "personal",
  Promotions: "promo",
  Studies: "studies",
  Review: "review",
};

/**
 * Reply tones (FR-06). Mirrors TONES in backend/orchestrator/schemas.py.
 *
 * "Default" is the neutral option and is not the same as Professional: it
 * means no tone instruction at all, so the reply matches the register of the
 * email being answered.
 */
export const TONES = [
  { key: "neutral", label: "Default", hint: "Match the original email" },
  { key: "professional", label: "Professional", hint: "Courteous and efficient" },
  { key: "formal", label: "Formal", hint: "No contractions, Yours sincerely" },
  { key: "casual", label: "Casual", hint: "Warmer and more relaxed" },
];
