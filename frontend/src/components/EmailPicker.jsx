/**
 * "Which email?" control shared by the Summarise, Draft and Voice views.
 *
 * The AI features all operate on exactly one message, so each of them needs the
 * same selection step. Sharing it keeps one behaviour: the currently selected
 * inbox row stays selected when you move between features.
 */
export default function EmailPicker({ emails, selected, onSelect, label = "Email" }) {
  return (
    <label className="picker">
      <span className="picker-label">{label}</span>
      <select
        className="picker-select"
        value={selected ?? ""}
        onChange={(e) => onSelect(e.target.value === "" ? null : Number(e.target.value))}
      >
        <option value="">Select an email…</option>
        {emails.map((e) => (
          <option key={e.id} value={e.id}>
            {e.from} — {e.subject}
          </option>
        ))}
      </select>
    </label>
  );
}
