import React from 'react';
import { BarRows } from './UsageCharts';
import BackupJobList from './BackupJobList';
import { BackupButton, BackupCard, BackupPill, muted, safeTime } from './BackupUI';

export default function BackupRestoreTest({ restore, jobs = [], migration, run, viewAs, runningKinds = [], onSelectJob }) {
  const last = restore?.last;
  const busy = runningKinds.includes('restore_test');
  const electionCheck = (migration?.checklist || []).find((c) => c.name === 'No election open');
  const electionOpen = electionCheck ? !electionCheck.ok : false;
  const chain = last?.result?.chain_verify || last?.result?.chain_results || [];
  const coverage = last?.result?.uncovered_collections || last?.result?.coverage_uncovered || last?.result?.coverage || [];
  const history = jobs.filter((j) => j.kind === 'restore_test').slice(0, 12).reverse();
  const runNow = () => {
    const start = async () => run('/restore-test/run', { override_election_guard: electionOpen }, {
      confirm: true, danger: true,
      message: electionOpen ? 'An election is open. A restore test adds load to MongoDB. Continue despite the election guard?' : 'Run the B2 restore test now? The isolated restore_test database will be flushed before loading and flushed again afterward unless keep-data is enabled.',
    });
    return start();
  };
  return <div className="perf-grid">
    <BackupCard title="Staging (restore test)" note="The isolated restore_test database is scratch space. The mirror is the continuously refreshed copy of live data.">
      <div className="perf-controls"><BackupPill state={last?.status || 'neutral'}>{last?.status ? last.status : 'Never run'}</BackupPill>
        <span style={muted}>Last run: {safeTime(last?.finished_at || last?.started_at)}{last?.duration_s != null ? ` · ${last.duration_s}s` : ''}</span>
      </div>
      {last?.error ? <p style={{ ...muted, color: 'var(--danger)' }}>{last.error}</p> : null}
      {last?.result?.reason ? <p style={muted}>{last.result.reason}</p> : null}
      <div className="perf-actions" style={{ marginTop: 12 }}>
        <BackupButton primary disabled={viewAs || busy} onClick={runNow}>{busy ? 'Restore test running…' : 'Run restore test now'}</BackupButton>
      </div>
      {electionOpen ? <p style={{ ...muted, color: 'var(--warning)' }}>An election is open. The button requires an explicit confirmation because of the additional database load.</p> : null}
      {viewAs ? <p style={muted}>Actions are disabled in a read-only view-as session.</p> : null}
    </BackupCard>
    <BackupCard title="Latest run steps">
      {last?.steps?.length ? <div style={{ display: 'grid', gap: 8 }}>{last.steps.map((step, i) => <div key={`${step.name}-${i}`} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, borderBottom: '1px solid var(--border-color)', paddingBottom: 7 }}>
        <BackupPill state={step.status}>{step.status || 'unknown'}</BackupPill><div style={{ minWidth: 0 }}><strong style={{ fontSize: 13 }}>{step.name}</strong><p style={muted}>{step.detail || 'No detail supplied.'}</p></div>
      </div>)}</div> : <p style={muted}>No restore-test step log is available yet.</p>}
    </BackupCard>
    <BackupCard title="Chain Verify results">
      {chain.length ? <div style={{ display: 'grid', gap: 8 }}>{chain.map((row) => <div key={row.tenant} className="perf-controls" style={{ justifyContent: 'space-between' }}>
        <span><strong>{row.tenant}</strong><span style={{ ...muted, display: 'block' }}>Head {row.head_hash ? `${row.head_hash.slice(0, 8)}…` : '—'} · {row.checkpoints_verified ?? 0} checkpoints</span></span>
        <BackupPill state={row.valid ? 'passed' : 'failed'}>{row.valid ? 'Passed' : 'Failed'}</BackupPill>
      </div>)}</div> : <p style={muted}>No per-organisation Chain Verify result is recorded in the latest job result.</p>}
    </BackupCard>
    <BackupCard title="Coverage audit and warnings">
      {coverage.length ? <BarRows items={coverage.map((x) => ({ label: typeof x === 'string' ? x : x.collection || x.name || JSON.stringify(x), value: 1, sub: 'Not covered by backup' }))} format={() => 'Warning'} /> : <p style={muted}>No explicit coverage warnings in the latest result. The coverage audit also appears in the Migration readiness checklist.</p>}
      {last?.result?.warnings?.length ? <ul style={{ paddingLeft: 18 }}>{last.result.warnings.map((w, i) => <li key={i} style={muted}>{typeof w === 'string' ? w : JSON.stringify(w)}</li>)}</ul> : null}
    </BackupCard>
    <BackupCard title="Recent restore tests" note="Last 12 records retained in job history. Weekly scheduling is managed outside the sleeping web service.">
      {history.length ? <BarRows items={history.map((j) => ({ label: safeTime(j.finished_at || j.started_at), value: ({ passed: 3, warning: 2, failed: 1, skipped: 0 })[j.status] ?? 0, sub: j.status }))} format={(v) => ({ 3: 'Passed', 2: 'Warning', 1: 'Failed', 0: 'Skipped' })[v] || '—'} /> : <p style={muted}>Never run. No next scheduled time has been confirmed by the backend yet.</p>}
      <p style={muted}>Expected next scheduled run: {safeTime(restore?.next_scheduled) === '—' ? 'Not configured' : safeTime(restore.next_scheduled)}</p>
    </BackupCard>
    <BackupJobList jobs={jobs.filter((j) => j.kind === 'restore_test')} title="Restore-test job details" limit={8} onSelectJob={onSelectJob} />
  </div>;
}
