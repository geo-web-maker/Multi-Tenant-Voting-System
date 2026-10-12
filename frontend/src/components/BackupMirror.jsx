import React from 'react';
import { BarRows } from './UsageCharts';
import BackupJobList from './BackupJobList';
import { BackupButton, BackupCard, BackupPill, bytesText, muted, safeTime, tileClass } from './BackupUI';

export default function BackupMirror({ mirror, jobs = [], run, viewAs, runningKinds = [] }) {
  const counts = (mirror?.counts || []).map((c) => ({ label: c.collection, value: Math.abs(Number(c.live || 0) - Number(c.mirror || 0)),
    sub: `Live ${c.live ?? '—'} · mirror ${c.mirror ?? '—'}${c.differs ? ' · count differs' : ''}` })).sort((a, b) => b.value - a.value);
  const busy = runningKinds.includes('mirror_sync');
  return <div className="perf-grid">
    <div className="perf-tiles">
      {[
        ['Mirror', mirror?.enabled ? 'Enabled' : 'Not configured'],
        ['Last successful sync', safeTime(mirror?.last_ok_at)],
        ['Mirror lag', mirror?.lag_minutes == null ? 'Unknown' : `${mirror.lag_minutes} min`],
        ['Latency', mirror?.ping_ms == null ? '—' : `${mirror.ping_ms} ms`],
        ['Storage', `${bytesText(mirror?.size_bytes)} / ${bytesText(mirror?.limit_bytes)}`],
        ['Consecutive failures', mirror?.consecutive_failures ?? 0],
      ].map(([label, value]) => <div key={label} className={tileClass()}><span style={muted}>{label}</span><strong style={{ overflowWrap: 'anywhere' }}>{value}</strong></div>)}
    </div>
    <BackupCard title="Mirror status" note="This is a warm copy from live, not a failover. Trust vote data only after Chain Verify passes.">
      <div className="perf-controls"><BackupPill state={mirror?.enabled ? (mirror?.last_error ? 'failed' : mirror?.last_ok_at ? 'passed' : 'neutral') : 'neutral'}>{!mirror?.enabled ? 'Not configured' : mirror?.last_error ? 'Warning' : mirror?.last_ok_at ? 'Healthy' : 'Collecting'}</BackupPill>
        <span style={muted}>Last mode: {mirror?.last_mode || '—'} · host fingerprint: {mirror?.second_host_fp ? `${String(mirror.second_host_fp).slice(0, 8)}…` : 'not recorded'}</span>
      </div>
      {mirror?.last_error ? <p style={{ ...muted, color: 'var(--danger)' }}>Last error: {mirror.last_error}</p> : null}
      <div className="perf-actions" style={{ marginTop: 12 }}>
        <BackupButton primary disabled={viewAs || busy || !mirror?.enabled} onClick={() => run('/mirror/sync', { mode: 'incr' }, { danger: true, message: 'Run a quick mirror sync from the live database?' })}>{busy ? 'Sync running…' : 'Sync now (Quick)'}</BackupButton>
        <BackupButton disabled={viewAs || busy || !mirror?.enabled} onClick={() => run('/mirror/sync', { mode: 'full' }, { danger: true, message: 'Run a full mirror reconciliation, including deletion reconciliation? This adds load to live MongoDB.' })}>Full reconcile</BackupButton>
        <BackupButton disabled={viewAs || runningKinds.includes('chain_verify') || !mirror?.enabled} onClick={() => run('/chain-verify', { target: 'mirror', tenant: 'all' }, { confirm: false })}>Chain Verify on mirror</BackupButton>
      </div>
      {viewAs ? <p style={muted}>Actions are disabled in a read-only view-as session.</p> : null}
    </BackupCard>
    <BackupCard title="Per-collection count differences" note="Collections with the largest absolute count differences appear first; count equality does not by itself prove content integrity.">
      <BarRows items={counts} format={(n) => `${n} diff`} empty="No mirror counts are available yet." />
    </BackupCard>
    <BackupJobList jobs={jobs.filter((j) => ['mirror_sync', 'chain_verify'].includes(j.kind))} title="Recent mirror and verification jobs" limit={8} />
  </div>;
}
