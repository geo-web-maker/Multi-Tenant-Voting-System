import React from 'react';
import api from '../api';
import { startPolling } from '../hooks/usePolling';

const PHASES = ['applications','vetting','campaign','voting','results'];
export default function DemoControlsPanel() {
  const [status, setStatus] = React.useState({ enabled: false, counts: {}, credentials: {} });
  const [reason, setReason] = React.useState('');
  const [days, setDays] = React.useState(3);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [now, setNow] = React.useState(Date.now());
  const load = React.useCallback(async () => { try { setStatus((await api.get('/superadmin/demo/status')).data); } catch { setStatus({ enabled: false, counts: {}, credentials: {} }); } }, []);
  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => startPolling(load, 10000), [load]);
  React.useEffect(() => { if (!status.enabled) return undefined; const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, [status.enabled]);
  const remainingMs = status.enabled && status.expires_at ? Math.max(0, new Date(status.expires_at).getTime() - now) : 0;
  const remainingSeconds = Math.floor(remainingMs / 1000);
  const remD = Math.floor(remainingSeconds / 86400);
  const remH = Math.floor((remainingSeconds % 86400) / 3600);
  const remM = Math.floor((remainingSeconds % 3600) / 60);
  const remS = remainingSeconds % 60;
  const countdown = status.enabled ? `${remD}d ${String(remH).padStart(2,'0')}h ${String(remM).padStart(2,'0')}m ${String(remS).padStart(2,'0')}s` : '—';
  const act = async (method, url, body = {}) => {
    setBusy(true); setMsg(''); try { const r = await api[method](url, body); setMsg(r.data?.status || 'Done.'); await load(); } catch (e) { setMsg(e.response?.data?.detail || 'Action failed.'); } finally { setBusy(false); }
  };
  const doReason = () => reason.trim().length >= 3 ? reason.trim() : null;
  const enable = () => { const r = doReason(); if (!r) return setMsg('Enter a reason first.'); return act('post','/superadmin/demo/enable',{reason:r,days:Number(days)}); };
  const reset = () => { const r = doReason(); if (!r) return setMsg('Enter a reason first.'); return act('post','/superadmin/demo/reset',{reason:r}); };
  const disable = () => { const r = doReason(); if (!r) return setMsg('Enter a reason first.'); return act('post','/superadmin/demo/disable',{reason:r}); };
  const extend = () => { const r = doReason(); if (!r) return setMsg('Enter a reason first.'); return act('post','/superadmin/demo/extend',{reason:r,days:Number(days)}); };
  const msgKind = /fail|enter a reason/i.test(msg) ? 'error' : 'ok';
  return <section className="perf-card card-pad" style={{ marginBottom: 16 }} aria-label="Demo controls">
    <h3 style={h3}>Demo controls</h3>
    <p className="perf-lead">Safe guided-demo mode: only reserved fake-number SMS is captured and all demo data is fenced for reset.</p>
    <div className="perf-row" style={{ marginTop: 0 }}>{status.enabled ? <>Enabled · expires {status.expires_at ? new Date(status.expires_at).toLocaleString() : 'soon'} · <strong>{countdown} remaining</strong></> : 'Disabled'}</div>
    <div className="perf-btnbar" style={{ marginTop: 12 }}>
      <input className="perf-field" style={{ flex: '1 1 200px' }} maxLength={300} placeholder="Reason (required)" aria-label="Reason" value={reason} onChange={e=>setReason(e.target.value)} />
      <input className="perf-field" style={{ width: 90 }} type="number" min="1" max="14" aria-label="Days" value={days} onChange={e=>setDays(e.target.value)} />
    </div>
    {!status.enabled ? <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 12 }}><button type="button" className="perf-btn perf-btn-primary" disabled={busy} onClick={enable}>Enable</button></div> : <>
      <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 12 }}>
        <button type="button" className="perf-btn perf-btn-primary" disabled={busy} onClick={()=>act('post','/superadmin/demo/seed')}>Seed demo data</button>
        <button type="button" className="perf-btn" disabled={busy} onClick={reset}>Reset demo</button>
        <button type="button" className="perf-btn" disabled={busy} onClick={extend}>Extend</button>
        <button type="button" className="perf-btn perf-btn-danger" disabled={busy} onClick={disable}>Disable</button>
      </div>
      <div style={{ marginTop: 12 }}><b style={{ fontSize: 13 }}>Jump to phase</b>
        <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 8 }}>{PHASES.map(p=><button type="button" key={p} className="perf-btn" disabled={busy} onClick={()=>act('post','/superadmin/demo/phase',{phase:p})}>{p}</button>)}</div>
      </div>
      <p className="perf-note">Demo voters: {status.counts?.voters || 0} · Applications: {status.counts?.applications || 0} · Candidates: {status.counts?.candidates || 0} · Inbox: {status.counts?.inbox || 0}</p>
      {Object.keys(status.credentials || {}).length > 0 && <details style={{marginTop:10}}><summary>Demo credentials</summary><pre style={pre}>{JSON.stringify(status.credentials,null,2)}</pre></details>}
    </>}
    {msg && <div role="status" className="perf-msg" data-kind={msgKind} style={{ marginTop: 10 }}>{msg}</div>}
  </section>;
}
const h3 = { margin: '0 0 6px', fontSize: 15 };
const pre = { fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 260, overflow: 'auto' };
