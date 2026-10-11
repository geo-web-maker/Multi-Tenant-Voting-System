import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api, { getErrorMessage } from '../api';
import usePolling from '../hooks/usePolling';
import { useRevealReady } from './RevealGroup';
import { BarRows } from './UsageCharts';
import { PerfChart, ChartLegend } from './PerfCharts';
import { fmtOps } from '../perfFormat';

const POLL_MS = 15000;
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const pctText = (share) => `${Math.round((share || 0) * 100)}%`;

/**
 * Every organisation together. The range comes from the Performance tab's shared range bar, so the whole tab
 * moves together like Site Usage. `onData` hands the response up so the main chart can reuse the combined series.
 */
export default function PerfOrgs({ range = '15m', live = true, refreshKey = 0, sinkType = '', cap = null, onData }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await api.get('/superadmin/performance/orgs', { params: { window: range } });
      const body = r.data || { rows: [] };
      setData(body); setError('');
      if (onData) onData(body);
    } catch (e) { setError(getErrorMessage(e, 'Could not load organisation load.')); }
  }, [range, onData]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount, on range change and on Refresh; setState runs after the awaited request
  useEffect(() => { load(); }, [load, refreshKey]);
  // The 7-day view reads the history sink, so it is loaded once per choice and never polled.
  usePolling(load, POLL_MS, live && range !== '7d');
  useRevealReady(!!data || !!error);

  const rows = useMemo(() => data?.rows || [], [data]);
  const items = useMemo(() => rows.map((r) => ({ ...r, label: r.name, value: r.ops })), [rows]);
  const lines = useMemo(() => rows.filter((r) => r.points).map((r) => ({ name: r.name, points: r.points })), [rows]);
  const busiest = rows.length > 1 && rows[0].share >= 0.5 ? rows[0] : null;
  const matched = data && data.window === range;
  const start = matched ? data.start : null;

  return (
    <section className="perf-card card-pad" style={{ gridColumn: '1 / -1' }}>
      <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>Organisations, all combined</h3>
      <p style={muted}>Every organisation shares the same database cap, so this is where to spot a busy one.</p>
      {error ? <p style={{ ...muted, color: 'var(--danger)', marginTop: 8 }}>{error}</p> : null}
      {range === '7d' && sinkType === 'mongo' ? <p style={{ ...muted, marginTop: 8 }}>The 7-day view reads the history sink and uses main-cluster operations on this sink.</p> : null}
      {matched && data.note ? <p style={{ ...muted, marginTop: 8 }}>{data.note}</p> : null}
      {busiest ? <p style={{ ...muted, color: 'var(--warning)', margin: '8px 0' }}>{busiest.name} is using {pctText(busiest.share)} of the load.</p> : null}
      {matched && lines.length ? (
        <div style={{ marginTop: 10 }}>
          <PerfChart lines={lines} cap={cap} range={range} startTs={start} stepS={data.step_s} label="Operations per second by organisation" />
          <ChartLegend items={lines} />
        </div>
      ) : null}
      <BarRows
        items={matched ? items : []}
        format={(v) => `${v} ops`}
        empty="No organisation traffic in this period."
        sub={(x) => `${pctText(x.share)} of load · ${fmtOps(x.ops_s)} ops/s avg · ${x.requests} requests · 5xx ${x.errors_5xx} · 429 ${x.throttled_429}`} />
      {range === '7d' && matched && data.covered_minutes < 10080 ? (
        <p style={{ ...muted, marginTop: 8 }}>Per-organisation history only exists from when this feature was deployed, so older days will be empty. Figures also reset if the history sink is off.</p>
      ) : null}
    </section>
  );
}
