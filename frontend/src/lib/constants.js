/**
 * Static UI data, extracted verbatim from the original single-file InboxIQ.jsx.
 *
 * CATEGORIES holds the four classes the classifier may return. The fifth UI
 * bucket, "Review", is defined separately below: it is a destination for
 * unverified labels (spec section 4.3), never a value the model can produce.
 */

import {
  Inbox, Languages, ListChecks, MessageSquareReply, Mic, Sparkles,
  SlidersHorizontal, Volume2,
} from "lucide-react";

export const ROTATING = [
  { icon: Sparkles, text: "Summarise unread emails in seconds" },
  { icon: ListChecks, text: "Auto-sort your inbox into smart categories" },
  { icon: Mic, text: "Control your inbox with your voice" },
  { icon: Languages, text: "Reply in any language, any tone" },
];

export const FEATURES = [
  { id: "inbox", label: "Inbox", icon: Inbox, group: "main" },
  { id: "summarise", label: "Summarise", icon: Sparkles, group: "ai", desc: "Condense unread emails into a 2–3 sentence brief." },
  { id: "categorise", label: "Auto-Categorise", icon: ListChecks, group: "ai", desc: "Sort every email into Work, Personal, Promotions & Studies." },
  { id: "reply", label: "Draft Reply", icon: MessageSquareReply, group: "ai", desc: "Generate a reply you review and approve before sending." },
  { id: "tone", label: "Tone & Translate", icon: SlidersHorizontal, group: "ai", desc: "Rewrite replies in any tone, or translate to any language." },
  { id: "speak", label: "Read Aloud", icon: Volume2, group: "voice", desc: "Listen to summaries with built-in text-to-speech." },
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

/** The four categories the classifier may return, in API casing. */
export const CLASSIFIER_CATEGORIES = ["Work", "Personal", "Promotions", "Studies"];

/** Maps an API category value onto the UI category key. */
export const API_TO_KEY = {
  Work: "work",
  Personal: "personal",
  Promotions: "promo",
  Studies: "studies",
  Review: "review",
};
