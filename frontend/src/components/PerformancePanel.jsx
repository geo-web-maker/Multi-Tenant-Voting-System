import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api, { getErrorMessage } from '../api';
import usePolling from '../hooks/usePolling';
import { DEFAULT_TZ } from '../tz';
import { LoadingBlock } from './Spinner.jsx';
import PerformanceSettings from './PerformanceSettings';
import PerfStorage from './PerfStorage';
import RevealGroup, { useRevealReady } from './RevealGroup';
import PerfOrgs from './PerfOrgs';
import AlertPanel from './AlertPanel';
import { BarRows } from './UsageCharts';
import { getTemplate } from '../template';
import { PerfChart, PerfLine } from './PerfCharts';
import {
  STATUS_LABEL, barPct, fmtMb, fmtMs, fmtOps, fmtUptime, headerLine, headroomText, sinkIsUnhealthy, sinkLine,
  statusColorVar, viewState,
} from '../perfFormat';

export { PerfLine };
const RANGES = [['15m', 'Last 15 min'], ['24h', 'Last 24 hours'], ['7d', 'Last 7 days']];
const RANGE_TITLE = { '15m': 'Last 15 minutes', '24h': 'Last 24 hours', '7d': 'Last 7 days' };

// Render free (0.1 CPU): each open tab costs real CPU on the server, so poll gently.
const POLL_MS = 15000;       // summary
const SLOW_POLL_MS = 30000;  // series, breakdown, slow list
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const STATUS_TONE = { ok: 'ok', busy: 'warn', critical: 'neg', throttling: 'neg', nodata: 'mute', paused: 'mute', off: 'mute' };

// Same panel as Site Usage: 16 px padding, 12 px radius, `card-pad` for the phone reset. The look itself lives in .perf-card (index.css).
function Card({ title, children }) {
  return (
    <section className="perf-card card-pad">
      {title ? <h3 style={h3}>{title}</h3> : null}
      {children}
    </section>
  );
}

function Pill({ state }) {
  const bp = getTemplate();   // render-time: null => the standard UI
  if (bp) return <bp.Pill tone={STATUS_TONE[state] || 'mute'}>{STATUS_LABEL[state] || state}</bp.Pill>;
  const color = `var(${statusColorVar(state)})`;
  return (
    <span className="perf-pill" style={{ border: `1px solid ${color}`, color, borderRadius: 999, padding: '2px 10px', fontSize: 13, fontWeight: 600 }}>
      {STATUS_LABEL[state] || state}
    </span>
  );
}

const pctText = (share) => `${Math.round((share || 0) * 100)}%`;
const TAB_LABEL = { collection: 'Collections', route: 'Routes' };
// One bar row per collection or route, like the Site Usage lists: the number is the bar, the detail sits underneath.
const BREAK_ITEMS = {
  collection: (r) => ({ label: r.name, value: r.ops, sub: `${pctText(r.share)} of operations · p95 ${fmtMs(r.p95_ms)}` }),
  route: (r) => ({ label: r.name, value: r.requests, sub: `${fmtOps(r.ops_per_request)} operations per request · p95 ${fmtMs(r.p95_ms)}` }),
};

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
  const [range, setRange] = useState('24h');   // 24 h by default: 15 minutes is too short for long-term monitoring
  const [live, setLive] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [orgData, setOrgData] = useState(null);   // the combined series for the 7-day chart comes from the organisations call

  const loadSummary = useCallback(async () => {
    const r = await api.get('/superadmin/performance/summary');
    setSummary(r.data); setError('');
  }, []);
  const loadSlow = useCallback(async () => {
    const [s, b, sl, sk] = await Promise.all([
      api.get('/superadmin/performance/timeseries', { params: { window: range === '24h' ? '24h' : '15m' } }),
      api.get('/superadmin/performance/breakdown', { params: { by } }),
      api.get('/superadmin/performance/slow'),
      api.get('/superadmin/performance/sink'),
    ]);
    setSeries(s.data); setRows(b.data); setSlow(sl.data.commands || []); setSink(sk.data);
  }, [by, range]);
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
  usePolling(loadSummary, POLL_MS, live);
  usePolling(loadSlow, SLOW_POLL_MS, live);

  const refreshNow = useCallback(() => {
    setRefreshKey((k) => k + 1);
    loadSummary().catch(() => {}); loadSlow().catch(() => {});
  }, [loadSummary, loadSlow]);

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
  // 15 min and 24 h come from the process-wide series; 7 days is the combined organisation series from the history sink.
  const wide7 = range === '7d';
  const chartPoints = wide7 ? (orgData?.window === '7d' ? orgData.total_points || [] : []) : opsSeries;
  const chartStart = wide7 ? (orgData?.window === '7d' ? orgData.start : null) : series?.points?.[0]?.t;
  const chartStep = wide7 ? orgData?.step_s : series?.step_s ?? (series?.points?.[1]?.t - series?.points?.[0]?.t);
  const chartReady = wide7 ? orgData?.window === '7d' : series?.window === (range === '24h' ? '24h' : '15m') || (range === '15m' && !!series);
  const chartCap = (range === '24h' || wide7 ? db.cap : series?.cap) || null;

  // [label, value, tone]: a tile turns red only when the number is something to act on.
  const healthTiles = [
    ['Requests / s', fmtOps(summary?.http?.rps)], ['Request p95', fmtMs(summary?.http?.p95_ms)],
    ['5xx errors (1 min)', summary?.http?.s5xx_1m ?? 0, (summary?.http?.s5xx_1m ?? 0) > 0 ? 'danger' : ''],
    ['429 throttled (1 min)', summary?.http?.s429_1m ?? 0, (summary?.http?.s429_1m ?? 0) > 0 ? 'warning' : ''],
    ['DB connections', `${db.pool?.in_use ?? 0} / ${db.pool?.max ?? 'n/a'}`],
    ['Waiting for a connection', db.pool?.waiting ?? 0, (db.pool?.waiting ?? 0) > 0 ? 'warning' : ''],
    ['DB command p95', fmtMs(db.latency_ms?.p95)], ['Event-loop lag p95', fmtMs(summary?.runtime?.loop_lag_ms?.p95)],
    ['Memory', fmtMb(summary?.runtime?.rss_mb)], ['CPU', `${summary?.runtime?.cpu_pct ?? 'n/a'}%`],
  ];

  if (error && !summary) {
    return <Card><p style={muted}>{error}</p><div className="perf-controls" style={{ marginTop: 12 }}><button type="button" className="perf-btn" onClick={retry}>Retry</button></div></Card>;
  }
  if (!summary) return <LoadingBlock />;
  if (state === 'off') {
    return <Card><p style={{ margin: 0 }}>Performance monitoring is off.</p><p style={muted}>Set PERF_ENABLED=true and restart to turn it on.</p></Card>;
  }

  const shown = state === 'collecting' ? 'nodata' : state;
  const showHeadroom = capped && !!headroomText(summary.election);
  const breakItems = (rows?.rows || []).map(BREAK_ITEMS[by]);
  const slowItems = slow.map((s) => ({ label: [s.command, s.collection].filter(Boolean).join(' · '), value: s.duration_ms, sub: (s.t || '').slice(11, 19) }));
  return (
    <div className="perf-grid">
      <section className="perf-card card-pad">
        <strong>{headerLine(config || { tier: summary.tier, ops_cap: db.cap, conn_cap: summary.conn_cap })}</strong>
        <p style={{ ...muted, marginTop: 4 }}>All organisations combined, one shared database cap. Figures cover this server process.</p>
        <p style={muted}>Uptime {fmtUptime(summary.uptime_s)}{summary.collecting_since ? ` · collecting since ${summary.collecting_since.slice(11, 16)} UTC` : ''}</p>
        {error ? <p style={{ ...muted, color: 'var(--danger)' }}>{error}</p> : null}
        <div className="perf-controls" style={{ marginTop: 12 }}>
          <div role="group" aria-label="Range" className="perf-seg">
            {RANGES.map(([v, l]) => (
              <button key={v} type="button" className="perf-btn" aria-pressed={range === v} onClick={() => setRange(v)}>{l}</button>
            ))}
          </div>
          <button type="button" className="perf-btn perf-btn-primary" onClick={refreshNow}>Refresh</button>
          <label className="perf-check"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Live updates (5 s)</label>
        </div>
      </section>

      <section aria-label="Server health">
        <div className="perf-tiles">
          {healthTiles.map(([k, v, tone]) => (
            <div key={k} className="perf-card card-pad perf-tile" style={tone ? { borderColor: `var(--${tone})` } : undefined}>
              <div style={muted}>{k}</div>
              <strong style={{ fontSize: 20, color: tone ? `var(--${tone})` : undefined }}>{v}</strong>
            </div>
          ))}
        </div>
      </section>

      <div className="perf-pair">
        <Card title="Database load">
          {state === 'collecting' ? <p style={muted}>Collecting data, give it a minute.</p> : null}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span className="perf-stat" data-testid="ops-now">{state === 'collecting' ? 'No data yet' : `${fmtOps(db.ops_s)}${capped ? ` / ${db.cap}` : ''}`}</span>
            {state !== 'collecting' ? <span style={muted}>ops/s</span> : null}
            <Pill state={shown} />
          </div>
          {capped && state !== 'collecting' ? (
            <div className="perf-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={barPct(db.ops_s, db.cap)}>
              <div style={{ width: `${barPct(db.ops_s, db.cap)}%`, height: '100%', background: `var(${statusColorVar(shown)})` }} />
            </div>
          ) : <div style={{ height: 10 }} />}
          <p style={muted}>10 s avg {fmtOps(db.ops_s_10s)} · 60 s avg {fmtOps(db.ops_s_60s)} · 15 min peak {fmtOps(db.peak_15m)}</p>
        </Card>

        {showHeadroom ? (
          <Card title="Voter headroom">
            <p className="perf-stat" style={{ fontSize: 20 }}>{headroomText(summary.election)}</p>
            <p style={{ ...muted, marginTop: 8 }}>{summary.election.ops_per_voter} database operations per voter ({summary.election.ops_per_voter_source === 'measured' ? 'measured' : 'from the performance audit'}).</p>
          </Card>
        ) : null}
      </div>

      <Card title={`Database operations, ${RANGE_TITLE[range].toLowerCase()}`}>
        <div style={{ opacity: chartReady ? 1 : 0.5, transition: 'opacity 0.15s' }}>
          <PerfChart lines={[{ name: 'Database operations', points: chartPoints }]} cap={chartCap} range={range}
            startTs={chartStart} stepS={chartStep} label="Database operations per second" fill fitData />
        </div>
        <div className="perf-legend">
          <span><i style={{ background: 'var(--perf-line)' }} />Operations per second</span>
          {chartCap ? <span><i style={{ background: 'var(--danger)' }} />Database cap, {chartCap} ops/s</span> : null}
        </div>
        <p style={muted}>
          {wide7
            ? 'Averaged per 2 hours, counting organisation traffic only. Dashed line is the database cap.'
            : `Dashed line is the database cap. Times are shown in ${DEFAULT_TZ}.`}
        </p>
      </Card>

      <AlertPanel alerts={summary.alerts || []}
        footer={(summary.recent_alerts || []).length ? `Last fired: ${summary.recent_alerts.slice(-3).map((a) => a.kind).join(', ')}` : null} />

      <PerfOrgs range={range} live={live} refreshKey={refreshKey} cap={db.cap || null} sinkType={sink?.type} onData={setOrgData} />

      <div className="perf-pair">
        <Card title="Where the load comes from">
          <div role="tablist" className="perf-seg" style={{ marginBottom: 8 }}>
            {Object.keys(TAB_LABEL).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={by === k} className="perf-btn" onClick={() => setBy(k)}>{TAB_LABEL[k]}</button>
            ))}
          </div>
          <BarRows items={breakItems} empty="No activity in the last 15 minutes." />
          <p style={{ ...muted, marginTop: 10 }}>Unattributed: {rows?.unattributed_pct === null || rows?.unattributed_pct === undefined ? 'n/a' : `${rows.unattributed_pct}%`} of operations come from collections that are not tied to a route.</p>
        </Card>

        <Card title="Slow commands">
          <BarRows items={slowItems} format={fmtMs} empty="None above the threshold." />
        </Card>
      </div>

      <Card title="History">
        <p style={muted}>24 hours are kept in memory; older history comes from the sink{sink?.type === 'mongo' ? ' and uses main-cluster operations on this sink' : ''}.</p>
        <div className="perf-controls" style={{ margin: '12px 0 8px' }}>
          <button type="button" className="perf-btn" onClick={loadHistory}>Load 7 days</button>
        </div>
        {history ? <p style={muted}>{history.minutes} minutes recorded, peak {fmtOps(history.peak)} ops/s.</p> : null}
        <p className="perf-sink" style={{ ...muted, marginTop: 8, color: sinkIsUnhealthy(sink) ? 'var(--danger)' : 'var(--text-muted)' }}>{sinkLine(sink)}{sink?.last_error ? ` · ${sink.last_error}` : ''}</p>
      </Card>

      <PerfStorage />

      <PerformanceSettings config={config} onSaved={onSaved} />

      <p style={muted}>Figures cover this process only and reset on restart. Atlas's own console remains the source of truth for the cap.</p>
    </div>
  );
}

export default function PerformancePanel() {
  return <RevealGroup text="Loading performance…"><PerformanceInner /></RevealGroup>;
}
