/* Extracted verbatim from InboxIQ.jsx. Still used for the two out-of-scope
   features (FR-06 tone, FR-07 translation), which stay honestly marked as not
   built rather than being removed from the nav. */
import { ChevronRight, Hammer } from "lucide-react";

export default function ComingSoon({ feature, onBack }) {
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

