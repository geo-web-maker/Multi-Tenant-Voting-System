import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import api, { getErrorMessage } from '../api';
import usePolling from '../hooks/usePolling';
import { DEFAULT_TZ, fmtZoned } from '../tz';
import { LoadingBlock } from './Spinner.jsx';
import RevealGroup, { useRevealReady } from './RevealGroup';
import { useConfirm, useToast } from './UIFeedback';
import BackupOverview from './BackupOverview';
import BackupConnections from './BackupConnections';
import BackupB2 from './BackupB2';
import BackupMirror from './BackupMirror';
import BackupRestoreTest from './BackupRestoreTest';
import BackupMigration from './BackupMigration';
import BackupSettings from './BackupSettings';
import BackupJobProgress from './BackupJobProgress';
import { BackupButton, BackupCard, BackupPill } from './BackupUI';
import { muted, cardClass } from './BackupUtils';

const ROOT = '/superadmin/backups';
const apiUrl = (path) => path.startsWith(ROOT) ? path : `${ROOT}${path.startsWith('/') ? path : `/${path}`}`;

function BackupRevealReady({ ready, children }) {
  useRevealReady(ready);
  return children;
}
const SUBTABS = [
  ['overview', 'Overview'], ['connections', 'Connections'], ['b2', 'Backblaze'],
  ['mirror', 'Second DB'], ['restore', 'Staging (restore test)'], ['migration', 'Migration'], ['settings', 'Settings'],
];
const ACTIVE_STATUSES = new Set(['queued', 'running']);

export default function BackupsPanel() {
  const [activeSubtab, setActiveSubtab] = useState('overview');
  const [range, setRange] = useState('24h');
  const [auto, setAuto] = useState(true);
  const [includeRestoreTest, setIncludeRestoreTest] = useState(false);
  const [summary, setSummary] = useState(null);
  // connections / b2 / mirror / migration come from /summary (the components already fall back to it).
  const connections = null, b2 = null, mirror = null;
  const [stats, setStats] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [migration, setMigration] = useState(null);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [jobDetail, setJobDetail] = useState(null);
  const [liveSteps, setLiveSteps] = useState({});
  const toast = useToast();
  const confirm = useConfirm();
  const viewAs = typeof window !== 'undefined' && !!sessionStorage.getItem('view_as');
  // The backend runs on a Render free instance (0.1 CPU). /summary already carries connections, b2, mirror and the
  // migration checklist, so the poll asks for that, the job list, and only the extras the open tab actually draws.
  const configLoaded = useRef(false);

  const loadJobs = useCallback(async ({ silent = true } = {}) => {
    try {
      const r = await api.get(`${ROOT}/jobs`, { params: { limit: 50 } });
      setJobs(r.data?.jobs || []);
    } catch (e) {
      if (!silent) toast(getErrorMessage(e, 'Unable to load backup job history.'), { kind: 'error' });
    }
  }, [toast]);

  const load = useCallback(async ({ silent = true } = {}) => {
    try {
      const names = ['summary', 'jobs'];
      const paths = [api.get(`${ROOT}/summary`), api.get(`${ROOT}/jobs`, { params: { limit: 50 } })];
      if (!configLoaded.current) { names.push('config'); paths.push(api.get(`${ROOT}/config`)); }
      const results = await Promise.allSettled(paths);
      // summary.migration is authoritative; clear any optimistic freeze override once fresh data arrives.
      const stateSetters = { summary: (v) => { setSummary(v); setMigration(null); }, jobs: (v) => setJobs(v?.jobs || []),
        config: (v) => { configLoaded.current = true; setConfig(v); } };
      const errors = [];
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') stateSetters[names[index]](result.value.data);
        else errors.push({ name: names[index], error: result.reason });
      });
      if (results[0].status === 'rejected') throw results[0].reason;
      // /summary degrades per section (200 + section_errors) instead of failing whole; say which parts are missing.
      const sectionErrors = results[0].value?.data?.section_errors || [];
      const failed = [...errors.map((e) => e.name), ...sectionErrors.map((e) => e.section)];
      setLoadError(failed.length ? `${[...new Set(failed)].join(', ')} data could not be refreshed.` : '');
      if (errors.length && !silent) toast(getErrorMessage(errors[0].error, 'Some backup information could not be loaded.'), { kind: 'error' });
    } catch (e) {
      const message = getErrorMessage(e, 'Unable to load Backups.');
      setLoadError(message);
      if (!silent) toast(message, { kind: 'error' });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  // Chart samples are written every 15-30 minutes, so they are fetched when the overview tab opens, the range
  // changes, or Refresh is pressed - not on every poll.
  const loadStats = useCallback(async () => {
    try { setStats((await api.get(`${ROOT}/stats`, { params: { range } })).data); } catch { /* keep the previous chart */ }
  }, [range]);

  // Initial load uses the same quiet polling callback; manual refresh reports errors through useToast.
  useEffect(() => { load({ silent: false }); }, [load]);
  useEffect(() => { if (activeSubtab === 'overview') loadStats(); }, [activeSubtab, loadStats]);
  usePolling(load, 60000, auto);
  const runningJobs = useMemo(() => jobs.filter((j) => ACTIVE_STATUSES.has(j.status)), [jobs]);
  const runningKinds = useMemo(() => runningJobs.map((j) => j.kind), [runningJobs]);
  const hasRunning = runningJobs.length > 0;
  usePolling(loadJobs, 3000, auto && hasRunning);
  // The list only carries each job's latest step; fetch the full step log for jobs that are still active.
  const runningIds = useMemo(() => runningJobs.map((j) => j.run_id).join(','), [runningJobs]);
  const loadLive = useCallback(async () => {
    const ids = runningIds ? runningIds.split(',') : [];
    if (!ids.length) { setLiveSteps({}); return; }
    const out = {};
    await Promise.all(ids.map(async (id) => {
      try { out[id] = (await api.get(`${ROOT}/jobs/${encodeURIComponent(id)}`)).data?.steps || []; } catch { /* keep list data */ }
    }));
    setLiveSteps(out);
  }, [runningIds]);
  useEffect(() => { loadLive(); }, [loadLive]);
  usePolling(loadLive, 3000, auto && hasRunning);

  const run = useCallback(async (path, body = {}, options = {}) => {
    const method = String(options.method || 'post').toLowerCase();
    const target = apiUrl(path);
    const wantsConfirm = options.confirm === true || (options.confirm !== false && (options.danger || !!options.message));
    if (viewAs) {
      toast('This action is disabled in a read-only view-as session.', { kind: 'error' });
      return null;
    }
    if (wantsConfirm) {
      const ok = await confirm(options.message || `Proceed with ${path}?`, {
        danger: options.danger !== false,
        confirmText: options.confirmText || (options.danger ? 'Continue' : 'Confirm'),
        requireText: options.requireText,
      });
      if (!ok) return null;
    }
    try {
      let response;
      if (method === 'get') response = await api.get(target, { params: body });
      else if (method === 'put') response = await api.put(target, body);
      else if (method === 'delete') response = await api.delete(target);
      else response = await api.post(target, body);
      const data = response?.data;
      if (data?.run_id) toast(`Job accepted: ${data.run_id}`, { kind: 'success' });
      else toast(options.success || 'Action completed.', { kind: 'success' });
      if (path === '/config') setConfig(data);
      if (path === '/freeze') setMigration((prev) => ({ ...(prev || {}), freeze: data }));
      if (method === 'delete' && path === '/freeze') setMigration((prev) => ({ ...(prev || {}), freeze: data }));
      await load({ silent: true });
      if (data?.run_id) await loadJobs({ silent: true });
      return data;
    } catch (e) {
      const message = getErrorMessage(e, `Unable to ${path.split('/').filter(Boolean).pop()?.replaceAll('-', ' ') || 'complete action'}.`);
      toast(message, { kind: 'error' });
      await load({ silent: true });
      return null;
    }
  }, [confirm, load, loadJobs, toast, viewAs]);

  const liftFreeze = useCallback(async () => {
    return run('/freeze', {}, { method: 'delete', danger: true, message: 'Lift the migration write freeze now? Writes will be allowed again.', success: 'Write freeze lifted.' });
  }, [run]);

  const saveConfig = useCallback(async (values) => {
    return run('/config', { values }, { method: 'put', confirm: false, success: 'Backup monitoring settings saved.' });
  }, [run]);

  const testConnections = useCallback(async () => {
    return run('/connections/test', {}, { confirm: false, success: 'Connection probes completed.' });
  }, [run]);

  const showJob = useCallback(async (runId) => {
    try {
      const res = await api.get(`${ROOT}/jobs/${encodeURIComponent(runId)}`);
      setJobDetail(res.data);
    } catch (e) { toast(getErrorMessage(e, 'Unable to load job details.'), { kind: 'error' }); }
  }, [toast]);

  const refresh = useCallback(() => { loadStats(); return load({ silent: false }); }, [load, loadStats]);

  if (loading && !summary) return <LoadingBlock text="Loading Backups…" />;
  if (!summary && loadError) return <BackupCard title="Backups unavailable"><p style={muted}>{loadError}</p><BackupButton primary onClick={refresh}>Retry</BackupButton></BackupCard>;

  const restore = summary?.restore || {};
  const activeContent = (() => {
    if (activeSubtab === 'overview') return <BackupOverview summary={summary || {}} stats={stats} range={range} jobs={jobs} includeRestoreTest={includeRestoreTest} setIncludeRestoreTest={setIncludeRestoreTest} onTab={setActiveSubtab} run={run} onSelectJob={showJob} viewAs={viewAs} migration={migration || summary?.migration} />;
    if (activeSubtab === 'connections') return <BackupConnections data={connections} summary={summary} onTest={testConnections} viewAs={viewAs} />;
    if (activeSubtab === 'b2') return <BackupB2 b2={b2 || summary?.b2} jobs={jobs} run={run} viewAs={viewAs} runningKinds={runningKinds} />;
    if (activeSubtab === 'mirror') return <BackupMirror mirror={mirror || summary?.mirror} jobs={jobs} run={run} viewAs={viewAs} runningKinds={runningKinds} />;
    if (activeSubtab === 'restore') return <BackupRestoreTest restore={restore} jobs={jobs} migration={migration || summary?.migration} run={run} viewAs={viewAs} runningKinds={runningKinds} onSelectJob={showJob} />;
    if (activeSubtab === 'migration') return <BackupMigration migration={migration || summary?.migration} jobs={jobs} run={run} liftFreeze={liftFreeze} viewAs={viewAs} runningKinds={runningKinds} />;
    return <BackupSettings config={config} save={saveConfig} viewAs={viewAs} />;
  })();

  return <div style={{ display: 'grid', gap: 16, minWidth: 0 }}>
    <BackupCard title="Backups" note="Backup monitoring, isolated restore verification, second-cluster mirror and safe migration controls.">
      <div className="perf-controls">
        <div role="group" aria-label="Statistics range" className="perf-seg">
          {[['24h', '24 hours'], ['7d', '7 days'], ['30d', '30 days']].map(([v, label]) => <button key={v} type="button" className="perf-btn" aria-pressed={range === v} onClick={() => setRange(v)}>{label}</button>)}
        </div>
        <BackupButton primary onClick={refresh}>Refresh</BackupButton>
        <label className="perf-check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-refresh (60 s)</label>
      </div>
      {loadError ? <p style={{ ...muted, color: 'var(--warning)' }}>{loadError}</p> : null}
      {viewAs ? <p style={muted}>Read-only view-as session. All backup, migration and settings actions are disabled.</p> : null}
    </BackupCard>

    <div role="tablist" aria-label="Backup sections" className="perf-seg" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {SUBTABS.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={activeSubtab === id} className="perf-btn" onClick={() => setActiveSubtab(id)}>{label}</button>)}
    </div>

    <BackupJobProgress jobs={jobs} liveSteps={liveSteps} onSelectJob={showJob} />

    <RevealGroup text="Loading backup monitoring…">
      <BackupRevealReady ready={!loading}>{activeContent}</BackupRevealReady>
    </RevealGroup>

    {jobDetail ? <div role="dialog" aria-modal="true" aria-labelledby="backup-job-details-title" className={cardClass()} style={{ minWidth: 0 }}>
      <div className="perf-controls" style={{ justifyContent: 'space-between' }}><h3 id="backup-job-details-title" style={{ margin: 0, fontSize: 15 }}>Job details</h3><BackupButton onClick={() => setJobDetail(null)}>Close</BackupButton></div>
      <div className="perf-controls"><strong>{jobDetail.kind || 'Job'}</strong><BackupPill state={jobDetail.status}>{jobDetail.status || 'unknown'}</BackupPill><span style={muted}>Started {jobDetail.started_at ? fmtZoned(jobDetail.started_at, DEFAULT_TZ) : '—'}</span></div>
      {jobDetail.error ? <p style={{ ...muted, color: 'var(--danger)' }}>{jobDetail.error}</p> : null}
      {jobDetail.steps?.length ? <div style={{ display: 'grid', gap: 8 }}>{jobDetail.steps.map((s, i) => <div key={`${s.name}-${i}`} style={{ borderBottom: '1px solid var(--border-color)', padding: '6px 0' }}><div className="perf-controls"><strong>{s.name}</strong><BackupPill state={s.status}>{s.status}</BackupPill></div><p style={muted}>{s.detail || '—'}</p>{s.at ? <p style={muted}>{fmtZoned(s.at, DEFAULT_TZ)}</p> : null}</div>)}</div> : <p style={muted}>No steps have been recorded.</p>}
      {jobDetail.result ? <details style={{ marginTop: 10 }}><summary>Result details</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 12 }}>{JSON.stringify(jobDetail.result, null, 2)}</pre></details> : null}
    </div> : null}
  </div>;
}
