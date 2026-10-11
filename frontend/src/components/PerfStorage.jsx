import React, { useCallback, useEffect, useState } from 'react';
import api, { getErrorMessage } from '../api';
import usePolling from '../hooks/usePolling';
import { useToast, useConfirm } from './UIFeedback';
import { fmtZoned, DEFAULT_TZ } from '../tz';

const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const STORES = [['mongo', 'MongoDB'], ['postgres', 'PostgreSQL']];
const NAME = { mongo: 'MongoDB', postgres: 'PostgreSQL' };

/**
 * Where Site Usage analytics are stored: switch between MongoDB and PostgreSQL, then copy the old history across.
 * The connection string stays on the server (ANALYTICS_POSTGRES_URL); this card only says whether it is set.
 */
export default function PerfStorage() {
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const r = await api.get('/superadmin/performance/storage'); setData(r.data || null); setError(''); }
    catch (e) { setError(getErrorMessage(e, 'Could not load storage settings.')); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const mig = data?.migration || { status: 'idle' };
  usePolling(load, 3000, mig.status === 'running');   // live progress only while a copy is running

  if (!data) return error ? <section className="perf-card card-pad"><p style={{ ...muted, color: 'var(--danger)' }}>{error}</p></section> : null;

  const active = data.mode;
  const switchTo = async (mode) => {
    if (mode === active || busy) return;
    const ok = await confirm(
      mode === 'postgres'
        ? 'Switch Site Usage to PostgreSQL? New activity is written there from now on. Older history stays in MongoDB until you press Migrate. Avoid doing this while voting is open.'
        : 'Switch Site Usage back to MongoDB? Activity recorded in PostgreSQL is not copied back, so those days will be missing from MongoDB.',
      { confirmText: `Switch to ${NAME[mode]}`, danger: mode === 'mongo' });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.put('/superadmin/performance/storage', { mode });
      setData(r.data); setError('');
      toast(`Site Usage now uses ${NAME[mode]}.`, { kind: 'success' });
    } catch (e) { toast(getErrorMessage(e, 'Could not switch storage.'), { kind: 'error' }); }
    finally { setBusy(false); }
  };
  const migrate = async () => {
    const ok = await confirm('Copy the MongoDB Site Usage history into PostgreSQL? It runs in the background, is safe to run again, and does not delete anything from MongoDB.', { confirmText: 'Migrate history' });
    if (!ok) return;
    setBusy(true);
    try { const r = await api.post('/superadmin/performance/storage/migrate'); setData(r.data); }
    catch (e) { toast(getErrorMessage(e, 'Could not start the migration.'), { kind: 'error' }); }
    finally { setBusy(false); }
  };

  const counts = mig.counts || {};
  const running = mig.status === 'running';
  const pgBlocked = active !== 'postgres' && !data.postgres_configured;
  return (
    <section className="perf-card card-pad" style={{ gridColumn: '1 / -1' }} aria-label="Site Usage storage">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>Site Usage storage</h3>
      <p style={muted}>Where Site Usage analytics are written. Voting data is not affected.</p>
      <div role="group" aria-label="Storage" className="perf-seg" style={{ margin: '12px 0 8px' }}>
        {STORES.map(([v, l]) => (
          <button key={v} type="button" className="perf-btn" aria-pressed={active === v} disabled={busy || running || (v === 'postgres' && pgBlocked)}
            onClick={() => switchTo(v)}>{l}{active === v ? ' (active)' : ''}</button>
        ))}
      </div>
      <p style={muted}>
        {NAME[active] || active} is active{data.chosen_in_app ? '' : ' (from the server setting)'}
        {data.switched_at ? ` · switched ${fmtZoned(data.switched_at, DEFAULT_TZ)}${data.switched_by ? ` by ${data.switched_by}` : ''}` : ''}.
      </p>
      {pgBlocked ? (
        <p style={{ ...muted, color: 'var(--warning)', marginTop: 6 }}>PostgreSQL is not set up on the server yet. Add ANALYTICS_POSTGRES_URL in Render, then redeploy.</p>
      ) : null}
      {error ? <p style={{ ...muted, color: 'var(--danger)', marginTop: 6 }}>{error}</p> : null}

      <h4 style={{ margin: '16px 0 6px', fontSize: 13, color: 'var(--text-muted)' }}>Move history to PostgreSQL</h4>
      {active !== 'postgres' ? (
        <p style={muted}>Switch to PostgreSQL first. Then this button copies the older history across.</p>
      ) : (
        <>
          {mig.status === 'idle' ? <p style={muted}>Older history is still in MongoDB until you migrate it.</p> : null}
          {running ? <p style={muted} role="status">Copying… {counts.counter_docs || 0} daily records and {counts.heat_docs || 0} click maps so far.</p> : null}
          {mig.status === 'done' ? (
            <p style={{ ...muted, color: 'var(--success)' }} role="status">
              {mig.message} {counts.counter_docs || 0} daily records and {counts.heat_docs || 0} click maps, up to {mig.cutoff}.
            </p>
          ) : null}
          {mig.status === 'failed' ? <p style={{ ...muted, color: 'var(--danger)' }} role="alert">{mig.message}</p> : null}
          <div className="perf-controls">
            <button type="button" className="perf-btn perf-btn-primary" disabled={busy || running} onClick={migrate}>
              {mig.status === 'idle' ? 'Migrate history' : running ? 'Migrating…' : 'Run migration again'}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
