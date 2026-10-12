import React, { useState } from 'react';
import { BackupCard, BackupPill } from './BackupUI';
import { durationText, muted, safeTime } from './BackupUtils';

export default function BackupJobList({ jobs = [], title = 'Recent jobs', limit = 8, onSelectJob }) {
  const [all, setAll] = useState(false);
  const sorted = [...jobs].sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0));
  const shown = all ? sorted : sorted.slice(0, limit);
  return <BackupCard title={title}>
    {!shown.length ? <p style={muted}>No jobs have run yet.</p> : <div style={{ display: 'grid', gap: 8 }}>
      {shown.map((job) => {
        const duration = job.finished_at && job.started_at ? (new Date(job.finished_at) - new Date(job.started_at)) / 1000 : null;
        const item = <div style={{ display: 'grid', gap: 4, minWidth: 0, textAlign: 'left' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
            <strong style={{ fontSize: 13, overflowWrap: 'anywhere' }}>{String(job.kind || 'job').replaceAll('_', ' ')}</strong>
            <BackupPill state={job.status}>{job.status || 'unknown'}</BackupPill>
          </div>
          <span style={muted}>Started {safeTime(job.started_at)} · {job.actor || job.trigger || 'system'}{duration != null ? ` · ${durationText(duration)}` : ''}</span>
          {job.steps?.length ? <span style={muted}>Current step: {job.steps[job.steps.length - 1]?.name || 'Queued'} — {job.steps[job.steps.length - 1]?.detail || job.steps[job.steps.length - 1]?.status || ''}</span> : null}
        </div>;
        return onSelectJob ? <button type="button" key={job.run_id || job._id} className="perf-btn" style={{ minHeight: 0, height: 'auto', padding: 10, textAlign: 'left', width: '100%' }} onClick={() => onSelectJob(job.run_id || job._id)}>{item}</button> : <div key={job.run_id || job._id} style={{ borderBottom: '1px solid var(--border-color)', padding: '7px 0' }}>{item}</div>;
      })}
      {sorted.length > limit ? <button type="button" className="perf-btn" style={{ marginTop: 8 }} onClick={() => setAll((v) => !v)} aria-expanded={all}>{all ? 'Show fewer' : `Show all ${sorted.length}`}</button> : null}
    </div>}
  </BackupCard>;
}
