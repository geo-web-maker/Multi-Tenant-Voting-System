// Voter headline numbers in the Blueprint look (BP-T8a). Same data, same words as the default VoterStats; counts only.
import { Meter } from './primitives.jsx';

const Card = ({ label, value, tone }) => (
  <div className="bp-card bp-stat">
    <div className="bp-mu">{label}</div>
    <div className={`bp-big${tone ? ` bp-${tone}` : ''}`}>{value}</div>
  </div>
);

export default function VoterStatsView({ d }) {
  const sms = d.sms || {};
  return (
    <div data-testid="voter-stats">
      <div className="bp-grid bp-g4 bp-k2">
        <Card label="Total voters" value={d.total} />
        <Card label="Voted" value={`${d.voted} (${d.turnout_pct}%)`} />
        <Card label="Not yet voted" value={d.not_voted} />
        <Card label="Phone on file" value={d.with_phone} />
        <Card label="No phone" value={d.without_phone} tone={d.without_phone ? 'neg' : ''} />
        <Card label="SMS sent" value={sms.sent_total ?? 0} />
        <Card label="SMS budget left" value={sms.budget_total ? `${sms.budget_left} / ${sms.budget_total}` : 'not set'} />
      </div>
      {d.sections.length === 0 && <p className="bp-mu">No voter fields are switched on, so there is no per-section breakdown.</p>}
      {d.sections.map((s) => (
        <div key={s.key} className="bp-card">
          <b>Voters by {s.label}</b>
          {s.groups.map((g) => (
            <Meter key={g.label} pct={Math.min(100, d.total ? (100 * g.registered) / d.total : 0)} accent>
              <div className="bp-t">
                <span style={{ overflowWrap: 'anywhere' }}>{g.label}</span>
                <span><b>{g.registered}</b> voters · {g.voted} voted ({g.pct}%)</span>
              </div>
            </Meter>
          ))}
        </div>
      ))}
    </div>
  );
}
