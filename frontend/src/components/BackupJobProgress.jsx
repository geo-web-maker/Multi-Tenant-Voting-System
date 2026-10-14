import React, { useEffect, useState } from 'react';
import { Spinner } from './Spinner.jsx';
import { BackupCard, BackupPill } from './BackupUI';
import { muted } from './BackupUtils';

const KIND_LABELS = {
  health_check: 'Running all checks', b2_backup: 'Creating Backblaze backup', b2_verify: 'Verifying newest backups',
  b2_selftest: 'Running B2 self-test', mirror_sync: 'Syncing second cluster', chain_verify: 'Verifying audit chains',
  restore_test: 'Running restore test', migration_plan: 'Planning migration', migration_copy: 'Copying data to target',
  migration_final: 'Final migration pass', migration_verify: 'Verifying migration',
};
const STEP_LABELS = {
  connections: 'Probing live and second databases', b2_verify: 'Verifying Backblaze backups', mirror_sync: 'Syncing second cluster',
  chain_live: 'Verifying live audit chains', chain_mirror: 'Verifying mirror audit chains', restore_test: 'Restore test',
};
// Steps a job is known to take, so the card can show what is still waiting. Other kinds only list steps as they finish.
const planned = (job) => job.kind !== 'health_check' ? [] :
  ['connections', 'b2_verify', 'mirror_sync', 'chain_live', 'chain_mirror', ...(job.params?.include_restore_test ? ['restore_test'] : [])];
const label = (n) => STEP_LABELS[n] || String(n || 'step').replaceAll('_', ' ');
const elapsed = (from, now) => {
  const s = Math.max(0, Math.floor((now - new Date(from).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};
const ICON = { passed: '✓', warning: '!', failed: '✕', skipped: '–' };

function JobRow({ job, steps, now, onSelectJob }) {
  const done = steps?.length ? steps : (job.steps || []);
  const plan = planned(job);
  const finished = new Set(done.map((s) => s.name));
  const pending = plan.filter((n) => !finished.has(n));
  const current = pending[0];
  const last = done[done.length - 1];
  const total = job.progress?.total || 0;
  const pct = total > 0 ? Math.min(100, Math.round((job.progress.done / total) * 100))
    : plan.length ? Math.round((plan.length - pending.length) / plan.length * 100) : null;
  const queued = job.status === 'queued';
  return <div className="perf-jobprog" role="status" aria-live="polite">
    <div className="perf-controls" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <Spinner size={16} /><strong style={{ fontSize: 14 }}>{KIND_LABELS[job.kind] || String(job.kind).replaceAll('_', ' ')}</strong>
      </span>
      <span style={muted}>{job.started_at ? elapsed(job.started_at, now) : ''}</span>
    </div>
    <div className="perf-jobprog-bar" aria-hidden="true"><span className={pct == null ? 'indeterminate' : ''} style={pct == null ? undefined : { width: `${Math.max(pct, 4)}%` }} /></div>
    <p style={{ ...muted, margin: '6px 0 0' }}>
      {queued ? 'Waiting to start…' : current ? `Now: ${label(current)}…` : last ? `Last finished: ${label(last.name)}${last.detail ? ` — ${last.detail}` : ''}` : 'Starting…'}
      {total > 0 ? ` (${job.progress.done} of ${total})` : pct != null ? ` (${plan.length - pending.length} of ${plan.length} steps)` : ''}
    </p>
    {done.length || pending.length ? <ul className="perf-jobprog-steps">
      {done.slice(-6).map((s, i) => <li key={`${s.name}-${i}`} data-s={s.status}><span aria-hidden="true">{ICON[s.status] || '•'}</span><span>{label(s.name)}{s.detail ? <em> — {String(s.detail)}</em> : null}</span><BackupPill state={s.status}>{s.status}</BackupPill></li>)}
      {pending.map((n, i) => <li key={n} data-s={i === 0 && !queued ? 'running' : 'pending'}><span aria-hidden="true">{i === 0 && !queued ? '…' : '○'}</span><span>{label(n)}</span><span style={muted}>{i === 0 && !queued ? 'in progress' : 'waiting'}</span></li>)}
    </ul> : null}
    {onSelectJob ? <button type="button" className="perf-btn" style={{ marginTop: 8 }} onClick={() => onSelectJob(job.run_id)}>Full details</button> : null}
  </div>;
}

export default function BackupJobProgress({ jobs = [], liveSteps = {}, onSelectJob }) {
  const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active.length) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active.length]);
  if (!active.length) return null;
  return <BackupCard title="Work in progress" note="Live status of background jobs. Safe to switch tabs; this updates every few seconds.">
    <div style={{ display: 'grid', gap: 14 }}>
      {active.map((job) => <JobRow key={job.run_id} job={job} steps={liveSteps[job.run_id]} now={now} onSelectJob={onSelectJob} />)}
    </div>
  </BackupCard>;
}
