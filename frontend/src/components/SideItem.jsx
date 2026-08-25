/* Extracted from InboxIQ.jsx.

   The "soon" badge is now read off the feature itself (f.soon) rather than
   taken from a prop the caller sets. Dashboard used to pass `soon` to every AI
   and Voice item unconditionally, so shipping an endpoint could never clear the
   badge -- somebody had to remember to delete a prop, and nobody did. Reading
   the flag from the same object that defines the feature means the sidebar and
   lib/constants.js can no longer disagree. */
export default function SideItem({ f, active, onClick, badge }) {
  const Icon = f.icon;
  const isActive = active === f.id;
  return (
    <button className={`nav-item ${isActive ? "active" : ""}`} onClick={() => onClick(f.id)}>
      <span className="nav-icon"><Icon size={18} strokeWidth={2.2} /></span>
      <span className="nav-label">{f.label}</span>
      {badge > 0 && <span className="nav-badge">{badge}</span>}
      {f.soon && <span className="nav-soon">soon</span>}
    </button>
  );
}
