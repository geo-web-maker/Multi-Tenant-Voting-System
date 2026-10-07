import React, { useEffect, useState } from 'react';
import api from '../api';
import { startPolling } from '../hooks/usePolling';
import { getTemplate } from '../template';

/**
 * CUSTOM-1 (restored): headline voter numbers for the superadmin Voters tab.
 * Counts only - never who a voter is or how anyone voted. Data: GET /admin/voters/stats.
 */
export default function VoterStats() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () => api.get('/admin/voters/stats')
      .then(r => { if (live) { setD(r.data); setErr(false); } })
      .catch(() => { if (live) setErr(true); });
    load();
    const stop = startPolling(load, 30000);
    return () => { live = false; stop(); };
  }, []);

  if (err && !d) return <p style={muted}>Could not load voter statistics.</p>;
  if (!d) return <p style={muted}>Loading voter statistics…</p>;
  const bp = getTemplate();
  if (bp?.VoterStatsView) return <bp.VoterStatsView d={d} />;   // all hooks are above: safe early return (R12)
  const sms = d.sms || {};
  return (
    <div data-testid="voter-stats">
      <div style={grid}>
        <Stat label="Total voters" value={d.total} />
        <Stat label="Voted" value={`${d.voted} (${d.turnout_pct}%)`} />
        <Stat label="Not yet voted" value={d.not_voted} />
        <Stat label="Phone on file" value={d.with_phone} />
        <Stat label="No phone" value={d.without_phone} color={d.without_phone ? 'var(--danger)' : undefined} />
        <Stat label="SMS sent" value={sms.sent_total ?? 0} />
        <Stat label="SMS budget left" value={sms.budget_total ? `${sms.budget_left} / ${sms.budget_total}` : 'not set'} />
      </div>
      {d.sections.length === 0 && <p style={muted}>No voter fields are switched on, so there is no per-section breakdown.</p>}
      {d.sections.map(s => (
        <div key={s.key} style={{ ...box, marginTop: 14 }}>
          <b style={{ fontSize: 13 }}>Voters by {s.label}</b>
          {s.groups.map(g => (
            <div key={g.label} style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                <span style={{ overflowWrap: 'anywhere' }}>{g.label}</span>
                <span style={{ whiteSpace: 'nowrap' }}><b>{g.registered}</b> voters · {g.voted} voted ({g.pct}%)</span>
              </div>
              <div style={{ height: 6, background: 'var(--border-color)', borderRadius: 3, overflow: 'hidden', marginTop: 3 }}>
                <div style={{ width: `${Math.min(100, d.total ? (100 * g.registered) / d.total : 0)}%`, height: '100%', background: 'var(--info)' }} />
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

const Stat = ({ label, value, color }) => (
  <div style={box}><small style={{ opacity: 0.6 }}>{label}</small><div style={{ fontWeight: 700, fontSize: 18, color }}>{value}</div></div>
);
const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 14, background: 'var(--bg-color)' };
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 };
const muted = { fontSize: 12, opacity: 0.65, margin: '8px 0' };
