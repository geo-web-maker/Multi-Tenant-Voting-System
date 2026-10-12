import React from 'react';
import { BarRows } from './UsageCharts';
import { PerfChart } from './PerfCharts';
import AlertPanel from './AlertPanel';
import BackupJobList from './BackupJobList';
import { BackupButton, BackupCard, BackupPill, bytesText, muted, safeTime, tileClass } from './BackupUI';

const SUBTABS = [
  ['connections', 'Connections', 'live_mongo'], ['b2', 'Backblaze', 'b2_backup_bucket'],
  ['mirror', 'Second DB', 'second_mirror'], ['restore', 'Staging (restore test)', 'restore_test'],
];
const val = (sample, key) => (sample?.[key] == null ? null : Number(sample[key]));
const toLine = (points, key) => points.map((p) => val(p, key));
const epoch = (p) => p ? new Date(p.at).getTime() / 1000 : null;

function StatChart({ title, points, keys, range, unit, scale = 1 }) {
  const ts = points?.length ? points : [];
  const start = epoch(ts[0]);
  const step = ts.length > 1 ? Math.max(1, Math.round((epoch(ts[ts.length - 1]) - start) / (ts.length - 1))) : (range === '24h' ? 900 : range === '7d' ? 900 : 900);
  const lines = keys.map(([key, name, color = '--perf-line']) => ({ name, color, points: toLine(ts, key).map((n) => n == null ? null : n / scale) }));
  return <BackupCard title={title}>
    {ts.length ? <PerfChart lines={lines} label={title} range={range} unit={unit} startTs={start} stepS={step} fitData /> : <p style={muted}>Collecting statistics. Samples are written every 15 minutes.</p>}
  </BackupCard>;
}

export default function BackupOverview({ summary, stats, range, jobs, includeRestoreTest, setIncludeRestoreTest, onTab, run, onSelectJob, viewAs, migration }) {
  const connections = summary?.connections || [];
  const findProbe = (id) => connections.find((p) => p.id === id);
  const restore = summary?.restore || {};
  const tiles = [
    { id: 'connections', title: 'Live database', probe: findProbe('live_mongo'), sub: findProbe('live_mongo')?.detail?.database || 'Connection has not been checked' },
    { id: 'mirror', title: 'Second cluster', probe: findProbe('second_mirror'), sub: summary?.mirror?.last_ok_at ? `Last sync ${safeTime(summary.mirror.last_ok_at)}` : 'Mirror has never synced' },
    { id: 'b2', title: 'Backblaze', probe: findProbe('b2_backup_bucket'), sub: summary?.b2?.object_count == null ? 'Backup inventory unavailable' : `${summary.b2.object_count} backup objects` },
    { id: 'restore', title: 'Restore test', probe: null, sub: restore.last ? `Last test ${safeTime(restore.last.finished_at)}` : 'Never run' },
  ];
  const running = summary?.jobs_running || [];
  const activeHealth = running.some((j) => j.kind === 'health_check');
  const electionOpen = (migration?.checklist || summary?.migration?.checklist || []).some((item) => item.name === 'No election open' && !item.ok);
  const restoreHistory = (jobs || []).filter((j) => j.kind === 'restore_test').slice(0, 12);
  return <div className="perf-grid">
    <BackupCard title="Backup infrastructure" note={`Last checked ${safeTime(summary?.checked_at)}. Live traffic is never routed through the mirror.`}>
      <div className="perf-controls">
        <BackupPill state={summary?.overall}>{summary?.overall ? summary.overall[0].toUpperCase() + summary.overall.slice(1) : 'Collecting'}</BackupPill>
        <BackupButton primary disabled={viewAs || activeHealth} title={viewAs ? 'Read-only view-as session' : activeHealth ? 'A health check is already running' : ''} onClick={() => run('/health-check', { include_restore_test: includeRestoreTest, override_election_guard: Boolean(includeRestoreTest && electionOpen) }, { confirm: true, danger: true, message: includeRestoreTest && electionOpen ? 'An election is open. Run all checks and explicitly override the extra restore-test load on the live database?' : includeRestoreTest ? 'Run all backup checks, including a B2 restore into the isolated staging database? This writes to the second cluster.' : 'Run all backup checks? This probes services and performs a quick mirror sync.', confirmText: 'Run checks' })}>{activeHealth ? 'Checks running…' : 'Run all checks'}</BackupButton>
        <label className="perf-check"><input type="checkbox" checked={includeRestoreTest} onChange={(e) => setIncludeRestoreTest(e.target.checked)} /> Include restore test</label>
      </div>
      {viewAs ? <p style={muted}>Actions are disabled in a read-only view-as session.</p> : null}
    </BackupCard>

    <AlertPanel alerts={summary?.alerts || []} />

    <div className="perf-tiles">
      {tiles.map((tile) => {
        const state = tile.id === 'restore' ? restore.last?.status || 'neutral' : tile.probe?.status || 'neutral';
        return <button type="button" key={tile.id} className={tileClass()} onClick={() => onTab(tile.id)} style={{ cursor: 'pointer', textAlign: 'left', color: 'inherit', minWidth: 0 }}>
          <div style={muted}>{tile.title}</div>
          <div style={{ margin: '7px 0' }}><BackupPill state={state}>{tile.id === 'restore' ? (restore.last?.status || 'Never run') : (tile.probe?.status || 'Not checked')}</BackupPill></div>
          <strong style={{ display: 'block', fontSize: 14, overflowWrap: 'anywhere' }}>{tile.sub}</strong>
        </button>;
      })}
    </div>

    <div className="perf-pair">
      <StatChart title="Database latency" points={stats?.points} keys={[["live_ping_ms", "Live DB", "--perf-line"], ["second_ping_ms", "Second cluster", "--info"]]} range={range} unit=" ms" />
      <StatChart title="Mirror lag" points={stats?.points} keys={[["mirror_lag_min", "Mirror lag"]]} range={range} unit=" min" />
    </div>
    <div className="perf-pair">
      <StatChart title="Backblaze stored data" points={stats?.points} keys={[["b2_total_bytes", "Stored data"]]} range={range} unit=" MB" scale={1024 * 1024} />
      <StatChart title="Newest backup age" points={stats?.points} keys={[["newest_backup_age_min", "Backup age"]]} range={range} unit=" min" />
    </div>
    <BackupCard title="Last 12 restore-test results" note="Missing history is shown as no data rather than as a healthy status.">
      {restoreHistory.length ? <BarRows items={restoreHistory.reverse().map((j) => ({ label: safeTime(j.finished_at || j.started_at), value: ({ passed: 3, warning: 2, failed: 1, skipped: 0 })[j.status] ?? 0, sub: j.status || 'unknown' }))} format={(v) => ({ 3: 'Passed', 2: 'Warning', 1: 'Failed', 0: 'Skipped' })[v] || '—'} /> : <p style={muted}>Never run. Staging is the dedicated restore_test database.</p>}
    </BackupCard>
    <BackupJobList jobs={jobs || []} title="Recent jobs" limit={8} onSelectJob={onSelectJob} />
  </div>;
}
