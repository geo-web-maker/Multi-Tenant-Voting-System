import React from 'react';
import { BarRows } from './UsageCharts';
import BackupJobList from './BackupJobList';
import { BackupButton, BackupCard, BackupPill, ChecklistRows, muted, safeTime, tileClass } from './BackupUI';

const CHECK_CAPTIONS = { 'No election open': 'Open now', 'No uncovered tenant-data collections': 'Not yet covered by backups' };

export default function BackupMigration({ migration, jobs = [], run, liftFreeze, viewAs, runningKinds = [] }) {
  const checklist = migration?.checklist || [];
  const freeze = migration?.freeze || {};
  const collections = [...(migration?.last_result?.collections || [])];
  const roleSwap = migration?.role_swap_checklist || {};
  const activeMigrationJob = ['migration_plan', 'migration_copy', 'migration_final', 'migration_verify'].find((k) => runningKinds.includes(k));
  const freezeJob = runningKinds.includes('migration_final');
  const latest = (kind) => jobs.filter((j) => j.kind === kind).sort((a, b) => String(b.started_at || '').localeCompare(String(a.started_at || '')))[0];
  const planDone = latest('migration_plan')?.status === 'passed';
  const copyDone = latest('migration_copy')?.status === 'passed';
  const noElectionOpen = checklist.find((item) => item.name === 'No election open')?.ok !== false;
  const action = (path, body, message, danger = true, requireText) => run(path, body, { danger, message, confirm: !!message, requireText });
  return <div className="perf-grid">
    <BackupCard title="Cutover readiness" note="Every required check must pass before switching the live MongoDB URL and frontend/backend URLs manually.">
      <div className="perf-controls"><BackupPill state={migration?.ready ? 'passed' : 'warning'}>{migration?.ready ? 'Ready to cut over' : 'Not ready to cut over'}</BackupPill>
        <span style={muted}>Freeze {freeze.active ? `active (${freeze.expires_in_seconds ?? 0}s remaining)` : 'inactive'}</span>
      </div>
      <ChecklistRows items={checklist} captions={CHECK_CAPTIONS} empty="Readiness checks have not run yet." />
      <div className="perf-tiles" style={{ marginTop: 12 }}>
        {[['Source', migration?.source?.label, migration?.source?.database], ['Target', migration?.target?.label, migration?.target?.database]].map(([label, main, db]) => <div className={tileClass()} key={label}><span className="perf-tile-label">{label}</span><strong>{main || 'Not configured'}</strong><span className="perf-tile-sub">{db || 'Database unknown'}</span></div>)}
      </div>
    </BackupCard>
    <BackupCard title="Migration workflow" note="Run in order: plan, copy rehearsal, enable write freeze, final pass, then verify. Environment-variable and domain cutover stays manual.">
      {activeMigrationJob ? <p style={{ ...muted, color: 'var(--info)' }}>Current job: {activeMigrationJob.replaceAll('_', ' ')} is running. Buttons for that job kind are disabled while it runs.</p> : null}
      <div className="perf-actions">
        <BackupButton disabled={viewAs || runningKinds.includes('migration_plan')} onClick={() => action('/migration/plan', {}, 'Run a read-only migration plan against the configured target?', false)}>Plan (dry run)</BackupButton>
        <BackupButton disabled={viewAs || !planDone || runningKinds.includes('migration_copy')} title={!planDone ? 'Run and complete the migration plan first.' : ''} onClick={() => action('/migration/run', { confirm: 'MIGRATE' }, 'Copy live data to the target as a rehearsal. This writes to the external target database.', true, 'MIGRATE')}>Copy (rehearsal)</BackupButton>
        <BackupButton primary disabled={viewAs || freeze.active || !copyDone || !noElectionOpen || runningKinds.includes('migration_final')} title={!copyDone ? 'Complete a migration rehearsal first.' : !noElectionOpen ? 'A write freeze is refused while any election is open.' : ''} onClick={() => action('/freeze', { minutes: 20 }, 'Start a 20-minute write freeze? It is refused while any election is open.')}>Start write freeze</BackupButton>
        <BackupButton disabled={viewAs || !freeze.active} onClick={liftFreeze}>Lift freeze</BackupButton>
        <BackupButton disabled={viewAs || !freeze.active || freezeJob || runningKinds.includes('migration_final')} onClick={() => action('/migration/final', { confirm: 'FINAL PASS' }, 'Run the final migration pass. This mirrors deletions to the target and should be done only while writes are frozen.', true, 'FINAL PASS')}>Final pass</BackupButton>
        <BackupButton disabled={viewAs || !copyDone || runningKinds.includes('migration_verify')} title={!copyDone ? 'Complete a migration copy first.' : ''} onClick={() => action('/migration/verify', {}, 'Verify source/target counts, content digests and target Chain Verify?', false)}>Verify migration</BackupButton>
      </div>
      {freeze.active ? <p style={{ ...muted, marginTop: 10 }}>Write freeze started {safeTime(freeze.started_at)}. It expires automatically; restarting the backend lifts it.</p> : <p style={muted}>Writes are currently allowed.</p>}
      {viewAs ? <p style={muted}>Actions are disabled in a read-only view-as session.</p> : null}
    </BackupCard>
    <BackupCard title="Per-collection migration results" note="Differences appear first. The list is capped at eight rows with expand/collapse.">
      <BarRows items={collections.sort((a, b) => Number(!a.verified) - Number(!b.verified) || Math.abs((b.source || 0) - (b.target || 0)) - Math.abs((a.source || 0) - (a.target || 0))).map((c) => ({ label: c.collection,
        value: Math.abs(Number(c.source || 0) - Number(c.target || 0)), sub: `Source ${c.source ?? '—'} · Target ${c.target ?? '—'} · ${c.verified == null ? 'not verified' : c.verified ? 'verified' : 'mismatch'}` }))} format={(n) => `${n} diff`} empty="No migration collection report has been recorded yet." />
    </BackupCard>
    <BackupCard title="Post-cutover role swap checklist" note="Informational until cutover; once the live database moves, the old Cape Town cluster becomes the second cluster.">
      {Object.entries(roleSwap).map(([key, ok]) => <div key={key} className="perf-controls" style={{ justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', padding: '6px 0' }}>
        <span style={{ fontSize: 13 }}>{({ second_cluster_not_migration_target: 'Second cluster is no longer the migration target', mirror_last_mode_full: 'First sync to second cluster used full reconciliation', no_temporary_dbs_on_live: 'No temporary mirror/staging DBs remain on live' })[key] || key.replaceAll('_', ' ')}</span><BackupPill state={ok ? 'passed' : 'warning'}>{ok ? 'Passed' : 'Pending'}</BackupPill>
      </div>)}
      <p style={muted}>After the environment swap, set SECOND_MONGO_URL to the old cluster, confirm the first sync mode is full, then manually drop only mirror and restore_test from the new live cluster in Atlas.</p>
    </BackupCard>
    <BackupJobList jobs={jobs.filter((j) => j.kind.startsWith('migration_'))} title="Recent migration jobs" limit={8} />
  </div>;
}
