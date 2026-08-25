/* Extracted verbatim from InboxIQ.jsx. */
export default function SideItem({ f, active, onClick, soon, badge }) {
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
