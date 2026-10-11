import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api, { getErrorMessage } from '../api';
import usePolling from '../hooks/usePolling';
import { useRevealReady } from './RevealGroup';
import { BarRows } from './UsageCharts';
import { fmtOps } from '../perfFormat';

const RANGES = [['15m', 'Last 15 min'], ['24h', 'Last 24 hours'], ['7d', 'Last 7 days']];
const AXIS_END = { '15m': '15 min ago', '24h': '24 h ago', '7d': '7 d ago' };
const POLL_MS = 15000;
// Distinct without relying on colour alone: colour plus dash pattern. Tokens only, so both templates and themes work.
const LINES = [
  { color: '--brand-primary', dash: '' }, { color: '--brand-accent', dash: '' },
  { color: '--text-color', dash: '7 4' }, { color: '--brand-primary', dash: '2 4' },
  { color: '--brand-accent', dash: '7 4' }, { color: '--text-muted', dash: '' },
];
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const pctText = (share) => `${Math.round((share || 0) * 100)}%`;
const seg = { padding: '6px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', font: 'inherit', cursor: 'pointer', minHeight: 44 };

/** Responsive multi-line SVG. Fonts are sized in viewBox units so labels stay readable when scaled to a phone. */
export function PerfMultiLine({ lines = [], cap = null, startLabel = '', unit = '/s' }) {
  const w = 600; const h = 190; const pad = { l: 46, r: 8, t: 10, b: 28 };
  const n = Math.max(0, ...lines.map((l) => l.points.length));
  const max = Math.max(0.1, ...lines.flatMap((l) => l.points));
  const iw = w - pad.l - pad.r; const ih = h - pad.t - pad.b;
  const x = (i) => pad.l + (n > 1 ? (i / (n - 1)) * iw : iw / 2);
  const y = (v) => pad.t + ih - (v / max) * ih;
  const maxLabel = max >= 10 ? Math.round(max) : Number(max.toFixed(2));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Operations per second by organisation" style={{ width: '100%', height: 'auto', display: 'block' }}>
      <line x1={pad.l} y1={pad.t + ih} x2={w - pad.r} y2={pad.t + ih} stroke="var(--border-color)" />
      <text x={2} y={pad.t + 12} fontSize="15" fill="var(--text-muted)">{maxLabel}{unit}</text>
      <text x={2} y={pad.t + ih} fontSize="15" fill="var(--text-muted)">0</text>
      <text x={pad.l} y={h - 6} fontSize="15" fill="var(--text-muted)">{startLabel}</text>
      <text x={w - pad.r} y={h - 6} fontSize="15" fill="var(--text-muted)" textAnchor="end">now</text>
      {cap && cap <= max ? <line x1={pad.l} x2={w - pad.r} y1={y(cap)} y2={y(cap)} stroke="var(--danger)" strokeDasharray="5 4" /> : null}
      {lines.map((l, k) => {
        const st = LINES[k % LINES.length];
        return <polyline key={l.name} fill="none" stroke={`var(${st.color})`} strokeWidth="2.5" strokeDasharray={st.dash || undefined}
          strokeLinejoin="round" points={l.points.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />;
      })}
    </svg>
  );
}

export default function PerfOrgs({ cap = null, sinkType = '' }) {
  const [range, setRange] = useState('15m');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await api.get('/superadmin/performance/orgs', { params: { window: range } });
      setData(r.data || { rows: [] }); setError('');
    } catch (e) { setError(getErrorMessage(e, 'Could not load organisation load.')); }
  }, [range]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount and on range change; setState runs after the awaited request
  useEffect(() => { load(); }, [load]);
  // The 7-day view reads the history sink, so it is loaded once per choice and never polled.
  usePolling(load, POLL_MS, range !== '7d');
  useRevealReady(!!data || !!error);

  const rows = useMemo(() => data?.rows || [], [data]);
  const items = useMemo(() => rows.map((r) => ({ ...r, label: r.name, value: r.ops })), [rows]);
  const lines = useMemo(() => rows.filter((r) => r.points).map((r) => ({ name: r.name, points: r.points })), [rows]);
  const busiest = rows.length > 1 && rows[0].share >= 0.5 ? rows[0] : null;
  const matched = data && data.window === range;

  return (
    <section className="perf-card card-pad" style={{ gridColumn: '1 / -1' }}>
      <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>Organisations, all combined</h3>
      <p style={muted}>Every organisation shares the same database cap, so this is where to spot a busy one.</p>
      <div role="group" aria-label="Range" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '10px 0' }}>
        {RANGES.map(([v, l]) => (
          <button key={v} type="button" aria-pressed={range === v} onClick={() => setRange(v)}
            style={range === v ? { ...seg, borderColor: 'var(--brand-primary)', fontWeight: 600 } : seg}>{l}</button>
        ))}
      </div>
      {error ? <p style={{ ...muted, color: 'var(--danger)' }}>{error}</p> : null}
      {range === '7d' && sinkType === 'mongo' ? <p style={muted}>The 7-day view reads the history sink and uses main-cluster operations on this sink.</p> : null}
      {matched && data.note ? <p style={muted}>{data.note}</p> : null}
      {busiest ? <p style={{ ...muted, color: 'var(--warning)', margin: '6px 0' }}>{busiest.name} is using {pctText(busiest.share)} of the load.</p> : null}
      {matched && lines.length ? (
        <>
          <PerfMultiLine lines={lines} cap={cap} startLabel={AXIS_END[range]} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px', margin: '8px 0 12px' }}>
            {lines.map((l, k) => {
              const st = LINES[k % LINES.length];
              return (
                <span key={l.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                  <svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke={`var(${st.color})`} strokeWidth="2.5" strokeDasharray={st.dash || undefined} /></svg>
                  {l.name}
                </span>
              );
            })}
          </div>
        </>
      ) : null}
      <BarRows
        items={matched ? items : []}
        format={(v) => `${v} ops`}
        empty="No organisation traffic in this period."
        sub={(x) => `${pctText(x.share)} of load · ${fmtOps(x.ops_s)} ops/s avg · ${x.requests} requests · 5xx ${x.errors_5xx} · 429 ${x.throttled_429}`} />
      {range === '7d' && matched && data.covered_minutes < 1440 ? (
        <p style={{ ...muted, marginTop: 8 }}>Per-organisation history only exists from when this feature was deployed, so older days will be empty. Figures also reset if the history sink is off.</p>
      ) : null}
    </section>
  );
}
