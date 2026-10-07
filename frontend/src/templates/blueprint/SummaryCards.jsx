// Headline cards for the observer consoles (BP-T8b). Same labels and values as the default summary row; presentation only.
export default function SummaryCards({ items }) {
  return (
    <div className="bp-grid bp-g4 bp-k2">
      {items.map(({ label, value }) => (
        <div key={label} className="bp-card bp-stat">
          <div className="bp-mu">{label}</div>
          <div className="bp-big bp-sm">{value}</div>
        </div>
      ))}
    </div>
  );
}
