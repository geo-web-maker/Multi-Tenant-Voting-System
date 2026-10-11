import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api, { getErrorMessage } from '../api';
import usePolling from '../hooks/usePolling';
import { LoadingBlock } from './Spinner.jsx';
import PerformanceSettings from './PerformanceSettings';
import RevealGroup, { useRevealReady } from './RevealGroup';
import PerfOrgs from './PerfOrgs';
import {
  STATUS_LABEL, barPct, fmtMb, fmtMs, fmtOps, fmtUptime, headerLine, headroomText, sinkIsUnhealthy, sinkLine,
  statusColorVar, viewState,
} from '../perfFormat';

const POLL_MS = 5000;        // summary
const SLOW_POLL_MS = 15000;  // series, breakdown, slow list
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', whiteSpace: 'nowrap' };
const td = { padding: '6px 8px', borderBottom: '1px solid var(--border-color)' };

function Card({ title, children, wide = false }) {
  return (
    <section className="perf-card card-pad" style={wide ? { gridColumn: '1 / -1' } : undefined}>
      {title ? <h3 style={h3}>{title}</h3> : null}
      {children}
    </section>
  );
}

function Pill({ state }) {
  const color = `var(${statusColorVar(state)})`;
  return (
    <span className="perf-pill" style={{ border: `1px solid ${color}`, color, borderRadius: 999, padding: '2px 10px', fontSize: 13, fontWeight: 600 }}>
      {STATUS_LABEL[state] || state}
    </span>
  );
}

/** Small responsive SVG line chart. Dashed reference line for the cap. Colours are tokens only. */
export function PerfLine({ points = [], cap = null, label, unit = '' }) {
  const w = 600; const h = 170; const pad = { l: 42, r: 6, t: 10, b: 18 };
  const vals = points.map((p) => (p === null || p === undefined ? null : p));
  const max = Math.max(1, cap || 0, ...vals.filter((v) => v !== null));
  const iw = w - pad.l - pad.r; const ih = h - pad.t - pad.b;
  const x = (i) => pad.l + (vals.length > 1 ? (i / (vals.length - 1)) * iw : iw / 2);
  const y = (v) => pad.t + ih - (v / max) * ih;
  const runs = []; let cur = [];
  vals.forEach((v, i) => { if (v === null) { if (cur.length) runs.push(cur); cur = []; } else cur.push(`${x(i)},${y(v)}`); });
  if (cur.length) runs.push(cur);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label} style={{ width: '100%', height: 'auto', display: 'block' }}>
      <line x1={pad.l} y1={pad.t + ih} x2={w - pad.r} y2={pad.t + ih} stroke="var(--border-color)" />
      <text x={2} y={pad.t + 12} fontSize="15" fill="var(--text-muted)">{Math.round(max)}{unit}</text>
      <text x={2} y={pad.t + ih} fontSize="15" fill="var(--text-muted)">0</text>
      {cap ? <line x1={pad.l} x2={w - pad.r} y1={y(cap)} y2={y(cap)} stroke="var(--danger)" strokeDasharray="5 4" /> : null}
      {runs.map((r, i) => <polyline key={i} fill="none" stroke="var(--brand-primary, currentColor)" strokeWidth="2" points={r.join(' ')} />)}
    </svg>
  );
}

function Table({ rows, cols }) {
  if (!rows.length) return <p style={muted}>No activity in the last 15 minutes.</p>;
  return (
    <div className="table-scroll">
      <table className="perf-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead><tr>{cols.map((c) => <th key={c.key} style={th}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>{cols.map((c) => <td key={c.key} data-l={c.label} style={td}>{c.render ? c.render(r) : r[c.key]}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const pctText = (share) => `${Math.round((share || 0) * 100)}%`;
const BREAK_COLS = {
  collection: [{ key: 'name', label: 'Collection' }, { key: 'ops', label: 'Ops' }, { key: 'share', label: 'Share', render: (r) => pctText(r.share) }, { key: 'p95_ms', label: 'p95', render: (r) => fmtMs(r.p95_ms) }],
  route: [{ key: 'name', label: 'Route' }, { key: 'requests', label: 'Requests' }, { key: 'ops_per_request', label: 'Ops/request', render: (r) => fmtOps(r.ops_per_request) }, { key: 'p95_ms', label: 'p95', render: (r) => fmtMs(r.p95_ms) }],
};
const TAB_LABEL = { collection: 'Collections', route: 'Routes' };

function PerformanceInner() {
  const [summary, setSummary] = useState(null);
  const [config, setConfig] = useState(null);
  const [series, setSeries] = useState(null);
  const [by, setBy] = useState('collection');
  const [rows, setRows] = useState(null);
  const [slow, setSlow] = useState([]);
  const [sink, setSink] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState('');

  const loadSummary = useCallback(async () => {
    const r = await api.get('/superadmin/performance/summary');
    setSummary(r.data); setError('');
  }, []);
  const loadSlow = useCallback(async () => {
    const [s, b, sl, sk] = await Promise.all([
      api.get('/superadmin/performance/timeseries', { params: { window: '15m' } }),
      api.get('/superadmin/performance/breakdown', { params: { by } }),
      api.get('/superadmin/performance/slow'),
      api.get('/superadmin/performance/sink'),
    ]);
    setSeries(s.data); setRows(b.data); setSlow(sl.data.commands || []); setSink(sk.data);
  }, [by]);
  const loadConfig = useCallback(async () => {
    const r = await api.get('/superadmin/performance/config');
    setConfig(r.data);
  }, []);

  const retry = useCallback(async () => {
    try { await Promise.all([loadSummary(), loadSlow(), loadConfig()]); } catch (e) { setError(getErrorMessage(e, 'Could not load.')); }
  }, [loadSummary, loadSlow, loadConfig]);
  // Initial load: the repo's usual exception for fetch-on-mount (see AnalyticsPanel, Results).
  // eslint-disable-next-line react-hooks/set-state-in-effect -- setState happens after the awaited requests
  useEffect(() => { retry(); }, [retry]);

  // usePolling already stops while the browser tab is hidden and resumes when it is visible again.
  usePolling(loadSummary, POLL_MS, true);
  usePolling(loadSlow, SLOW_POLL_MS, true);

  const onSaved = useCallback((cfg) => { setConfig(cfg); loadSummary().catch(() => {}); }, [loadSummary]);

  const loadHistory = async () => {
    const to = Math.floor(Date.now() / 1000);
    try {
      const r = await api.get('/superadmin/performance/history', { params: { from: to - 7 * 86400, to } });
      const mins = (r.data.minutes || []).filter((m) => m && m.ops !== null && m.ops !== undefined);
      setHistory({ sink: r.data.sink, minutes: mins.length, peak: mins.reduce((a, m) => Math.max(a, m.ops / 60), 0), main: !!r.data.uses_main_cluster });
    } catch (e) { setError(getErrorMessage(e, 'Could not load history.')); }
  };

  const state = viewState(summary);
  const db = summary?.db || {};
  const capped = !!db.cap;
  // Hold the whole page behind one spinner until every part has data, so sections appear together (RevealGroup).
  useRevealReady(!!summary && !!series);
  const opsSeries = useMemo(() => (series?.points || []).map((p) => (p.ops === undefined ? null : p.ops)), [series]);

  const healthTiles = [
    ['Requests / s', fmtOps(summary?.http?.rps)], ['Request p95', fmtMs(summary?.http?.p95_ms)],
    ['5xx errors (1 min)', summary?.http?.s5xx_1m ?? 0], ['429 throttled (1 min)', summary?.http?.s429_1m ?? 0],
    ['DB connections', `${db.pool?.in_use ?? 0} / ${db.pool?.max ?? 'n/a'}`], ['Waiting for a connection', db.pool?.waiting ?? 0],
    ['DB command p95', fmtMs(db.latency_ms?.p95)], ['Event-loop lag p95', fmtMs(summary?.runtime?.loop_lag_ms?.p95)],
    ['Memory', fmtMb(summary?.runtime?.rss_mb)], ['CPU', `${summary?.runtime?.cpu_pct ?? 'n/a'}%`],
  ];

  if (error && !summary) {
    return <Card><p style={muted}>{error}</p><button type="button" className="perf-btn" onClick={retry}>Retry</button></Card>;
  }
  if (!summary) return <LoadingBlock />;
  if (state === 'off') {
    return <Card><p style={{ margin: 0 }}>Performance monitoring is off.</p><p style={muted}>Set PERF_ENABLED=true and restart to turn it on.</p></Card>;
  }

  const shown = state === 'collecting' ? 'nodata' : state;
  return (
    <div className="perf-grid" style={{ display: 'grid', gap: 12 }}>
      <Card>
        <strong>{headerLine(config || { tier: summary.tier, ops_cap: db.cap, conn_cap: summary.conn_cap })}</strong>
        <p style={muted}>All organisations combined, one shared database cap. Figures cover this server process.</p>
        <p style={muted}>Uptime {fmtUptime(summary.uptime_s)}{summary.collecting_since ? ` · collecting since ${summary.collecting_since.slice(11, 16)} UTC` : ''}</p>
        {error ? <p style={{ ...muted, color: 'var(--danger)' }}>{error}</p> : null}
      </Card>

      <Card title="Database load">
        {state === 'collecting' ? <p style={muted}>Collecting data, give it a minute.</p> : null}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 32, fontWeight: 700 }} data-testid="ops-now">{state === 'collecting' ? 'No data yet' : `${fmtOps(db.ops_s)}${capped ? ` / ${db.cap}` : ''}`}</span>
          {state !== 'collecting' ? <span style={muted}>ops/s</span> : null}
          <Pill state={shown} />
        </div>
        {capped && state !== 'collecting' ? (
          <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={barPct(db.ops_s, db.cap)}
            style={{ height: 10, borderRadius: 6, background: 'var(--border-color)', margin: '10px 0', overflow: 'hidden' }}>
            <div style={{ width: `${barPct(db.ops_s, db.cap)}%`, height: '100%', background: `var(${statusColorVar(shown)})` }} />
          </div>
        ) : null}
        <p style={muted}>10 s avg {fmtOps(db.ops_s_10s)} · 60 s avg {fmtOps(db.ops_s_60s)} · 15 min peak {fmtOps(db.peak_15m)}</p>
      </Card>

      {capped && headroomText(summary.election) ? (
        <Card title="Voter headroom">
          <p style={{ margin: 0 }}>{headroomText(summary.election)}</p>
          <p style={muted}>{summary.election.ops_per_voter} database operations per voter ({summary.election.ops_per_voter_source === 'measured' ? 'measured' : 'from the performance audit'}).</p>
        </Card>
      ) : null}

      <Card title="Last 15 minutes">
        <PerfLine points={opsSeries} cap={series?.cap || null} label="Database operations per second" unit="/s" />
      </Card>

      <PerfOrgs cap={db.cap || null} sinkType={sink?.type} />

      <Card title="Server health" wide>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          {healthTiles.map(([k, v]) => (
            <div key={k}><div style={muted}>{k}</div><strong style={{ fontSize: 18 }}>{v}</strong></div>
          ))}
        </div>
      </Card>

      <Card title="Where the load comes from">
        <div role="tablist" style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          {Object.keys(TAB_LABEL).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={by === k} className="perf-btn" onClick={() => setBy(k)}>{TAB_LABEL[k]}</button>
          ))}
        </div>
        <Table rows={rows?.rows || []} cols={BREAK_COLS[by]} />
        <p style={muted}>Unattributed: {rows?.unattributed_pct === null || rows?.unattributed_pct === undefined ? 'n/a' : `${rows.unattributed_pct}%`} of operations come from collections that are not tied to a route.</p>
      </Card>

      <Card title="Slow commands">
        {slow.length ? (
          <Table rows={slow.map((s, i) => ({ ...s, name: `${s.t}-${i}` }))} cols={[
            { key: 't', label: 'Time', render: (r) => (r.t || '').slice(11, 19) },
            { key: 'command', label: 'Command' }, { key: 'collection', label: 'Collection' },
            { key: 'duration_ms', label: 'Duration', render: (r) => fmtMs(r.duration_ms) }]} />
        ) : <p style={muted}>None above the threshold.</p>}
      </Card>

      <Card title="Alerts">
        {(summary.alerts || []).length ? summary.alerts.map((a) => (
          <p key={a.kind} role="alert" style={{ margin: '0 0 6px', color: a.level === 'critical' ? 'var(--danger)' : 'var(--warning)' }}>{a.message}</p>
        )) : <p style={muted}>No active alerts.</p>}
        {(summary.recent_alerts || []).length ? <p style={muted}>Last fired: {summary.recent_alerts.slice(-3).map((a) => a.kind).join(', ')}</p> : null}
      </Card>

      <Card title="History">
        <p style={muted}>24 hours are kept in memory; older history comes from the sink{sink?.type === 'mongo' ? ' and uses main-cluster operations on this sink' : ''}.</p>
        <button type="button" className="perf-btn" onClick={loadHistory}>Load 7 days</button>
        {history ? <p style={muted}>{history.minutes} minutes recorded, peak {fmtOps(history.peak)} ops/s.</p> : null}
        <p className="perf-sink" style={{ ...muted, marginTop: 8, color: sinkIsUnhealthy(sink) ? 'var(--danger)' : 'var(--text-muted)' }}>{sinkLine(sink)}{sink?.last_error ? ` · ${sink.last_error}` : ''}</p>
      </Card>

      <PerformanceSettings config={config} onSaved={onSaved} />

      <p style={muted}>Figures cover this process only and reset on restart. Atlas's own console remains the source of truth for the cap.</p>
    </div>
  );
}

export default function PerformancePanel() {
  return <RevealGroup text="Loading performance…"><PerformanceInner /></RevealGroup>;
}
