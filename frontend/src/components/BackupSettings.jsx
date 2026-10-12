import React, { useEffect, useState } from 'react';
import { BackupButton, BackupCard, muted } from './BackupUI';

const NUMBER_FIELDS = [
  ['full_backup_active_hours', 'Full backup max age during an open election (hours)'],
  ['full_backup_idle_hours', 'Full backup max age while idle (hours)'],
  ['mirror_lag_active_minutes', 'Mirror lag warning during an open election (minutes)'],
  ['mirror_lag_idle_minutes', 'Mirror lag warning while idle (minutes)'],
  ['mirror_size_warn_bytes', 'Mirror size warning threshold (bytes)'],
  ['restore_test_warn_days', 'Restore-test warning age (days)'],
  ['probe_slow_ms', 'Mongo/Postgres slow threshold (ms)'],
  ['b2_slow_ms', 'B2 slow threshold (ms)'],
  ['sampling_minutes', 'Statistics sampling interval (minutes)'],
];

export default function BackupSettings({ config, save, viewAs }) {
  const [values, setValues] = useState(config?.values || {});
  const [saving, setSaving] = useState(false);
  useEffect(() => { setValues(config?.values || {}); }, [config]);
  const set = (key, value) => setValues((prev) => ({ ...prev, [key]: value }));
  const submit = async (event) => {
    event.preventDefault(); setSaving(true);
    try { await save(values); } finally { setSaving(false); }
  };
  return <div className="perf-grid">
    <form onSubmit={submit} className="perf-grid" style={{ gap: 16 }}>
      <div className="perf-pair">
        <BackupCard title="Alert thresholds">
          <div style={{ display: 'grid', gap: 12 }}>
            {NUMBER_FIELDS.map(([key, label]) => <label className="perf-field" key={key}>{label}
              <input type="number" min={key === 'sampling_minutes' ? 5 : 1} max={key === 'sampling_minutes' ? 60 : undefined} step="1" required value={values[key] ?? ''} onChange={(e) => set(key, e.target.value === '' ? '' : Number(e.target.value))} disabled={viewAs} />
            </label>)}
          </div>
        </BackupCard>
        <BackupCard title="Schedules and flags">
          <div style={{ display: 'grid', gap: 12 }}>
            <label className="perf-check"><input type="checkbox" checked={!!values.restore_test_weekly} onChange={(e) => set('restore_test_weekly', e.target.checked)} disabled={viewAs} /> Weekly restore test enabled</label>
            <label className="perf-check"><input type="checkbox" checked={!!config?.environment?.restore_test_keep_data} readOnly disabled /> RESTORE_TEST_KEEP_DATA — keep staging data after a restore test (environment variable)</label>
            <p style={muted}>When enabled, the scratch database is retained after a run for inspection. It is still flushed at the start of every run and is separate from the always-fresh mirror. Change this flag only in the deployment environment.</p>
            <p style={muted}>Scheduling must use an external scheduler because a free Render web service may sleep. The saved sampling interval is a target: update the external probe workflow/cron to match it (default 15 minutes). The weekly flag is stored here; it does not install a scheduler on Render.</p>
          </div>
        </BackupCard>
      </div>
      <BackupCard title="Save monitoring settings" note={config?.updated_at ? `Last saved ${config.updated_at}${config.updated_by ? ` by ${config.updated_by}` : ''}.` : 'Settings have not yet been loaded from the backend.'}>
        <BackupButton type="submit" primary disabled={viewAs || saving}>{saving ? 'Saving…' : 'Save settings'}</BackupButton>
        {viewAs ? <p style={muted}>Settings are read-only in a view-as session.</p> : null}
      </BackupCard>
    </form>
  </div>;
}
