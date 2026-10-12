import React, { useState } from 'react';
import { BarRows } from './UsageCharts';
import BackupJobList from './BackupJobList';
import { BackupButton, BackupCard, BackupPill, bytesText, muted, safeTime, tileClass } from './BackupUI';

export default function BackupB2({ b2, jobs = [], run, viewAs, runningKinds = [] }) {
  const [tenant, setTenant] = useState('');
  const [kind, setKind] = useState('full');
  const tenants = b2?.tenants || [];
  const chosenTenant = tenant || tenants[0]?.tenant || 'default';
  const busy = runningKinds.includes('b2_backup');
  const rows = tenants.map((t) => ({ label: t.slug || t.tenant, value: Number(t.bytes_gz) || 0,
    sub: `Full ${safeTime(t.last_full_at)} · Incremental ${safeTime(t.last_incr_at)} · age ${t.age_minutes == null ? 'never' : `${Math.round(t.age_minutes)} min`}` }));
  const totals = b2?.totals || {};
  return <div className="perf-grid">
    <BackupCard title="Routine backups by organisation" note="Newest full and incremental backup, backup age and last recorded bytes per organisation.">
      <BarRows items={rows} format={bytesText} />
      <div className="perf-tiles" style={{ marginTop: 12 }}>
        {[
          ['Routine', totals.routine_bytes], ['Safety', totals.safety_bytes], ['Milestone', totals.milestone_bytes], ['Cap', totals.cap_bytes],
        ].map(([label, value]) => <div className={tileClass()} key={label}><span style={muted}>{label} lock class</span><strong>{bytesText(value)}</strong></div>)}
      </div>
      <p style={muted}>Objects: {b2?.object_count ?? 'not available'} · Asset failures: {b2?.asset_failures ?? 0}</p>
      {b2?.last_failure ? <p style={{ ...muted, color: 'var(--danger)' }}>Latest failure: {typeof b2.last_failure === 'string' ? b2.last_failure : `${b2.last_failure.tenant || 'backup'}: ${b2.last_failure.error || 'backup failed'}`}</p> : null}
    </BackupCard>
    <BackupCard title="Back up now" note="A manual backup writes data to B2 and is audited. Keep the tab open to monitor its job record.">
      <div className="perf-controls">
        <label className="perf-field">Organisation
          <select value={chosenTenant} onChange={(e) => setTenant(e.target.value)} disabled={viewAs || !tenants.length}>
            {tenants.map((t) => <option key={t.tenant} value={t.tenant}>{t.slug || t.tenant}</option>)}
          </select>
        </label>
        <label className="perf-field">Backup kind
          <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={viewAs}><option value="full">Full</option><option value="incr">Incremental</option></select>
        </label>
        <BackupButton primary disabled={viewAs || busy || !tenants.length} onClick={() => run('/b2/run', { tenant: chosenTenant, kind, force: true }, { danger: true, message: 'Create a new locked B2 backup for this organisation now?' })}>{busy ? 'Backup running…' : 'Back up now'}</BackupButton>
      </div>
      <div className="perf-actions" style={{ marginTop: 10 }}>
        <BackupButton disabled={viewAs || runningKinds.includes('b2_verify')} onClick={() => run('/b2/verify', {}, { confirm: false })}>Verify newest backups</BackupButton>
        <BackupButton disabled={viewAs || runningKinds.includes('b2_selftest')} onClick={() => run('/b2/selftest', {}, { danger: true, message: 'Run the B2 self-test? It creates and reads back a test object using the configured retention lock.' })}>Run B2 self-test</BackupButton>
      </div>
      {viewAs ? <p style={muted}>Actions are disabled in a read-only view-as session.</p> : null}
    </BackupCard>
    <BackupJobList jobs={jobs.filter((j) => ['b2_backup', 'b2_verify', 'b2_selftest'].includes(j.kind))} title="Recent Backblaze jobs" limit={8} />
  </div>;
}
