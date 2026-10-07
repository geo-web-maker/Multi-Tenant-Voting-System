import React from 'react';
import api from '../api';
import { getTemplate } from '../template';

const PHASES = ['applications','vetting','campaign','voting','results'];
export default function DemoControlsPanel() {
  const bp = getTemplate(); const k = bp?.cls;
  const [status, setStatus] = React.useState({ enabled: false, counts: {}, credentials: {} });
  const [reason, setReason] = React.useState('');
  const [days, setDays] = React.useState(3);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [now, setNow] = React.useState(Date.now());
  const load = React.useCallback(async () => { try { setStatus((await api.get('/superadmin/demo/status')).data); } catch { setStatus({ enabled: false, counts: {}, credentials: {} }); } }, []);
  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => { const id = setInterval(load, 10000); return () => clearInterval(id); }, [load]);
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
  return <div style={box} className={k?.card}>
    <h4 className={k?.sec} style={{margin:'0 0 4px'}}>Demo controls</h4>
    <p style={{fontSize:12,opacity:.65,margin:'0 0 12px'}}>Safe guided-demo mode: only reserved fake-number SMS is captured and all demo data is fenced for reset.</p>
    <div style={notice}>{status.enabled ? <>Enabled · expires {status.expires_at ? new Date(status.expires_at).toLocaleString() : 'soon'} · <strong>{countdown} remaining</strong></> : 'Disabled'}</div>
    <div style={grid}><input style={inp} maxLength={300} placeholder="Reason (required)" value={reason} onChange={e=>setReason(e.target.value)} /><input style={{...inp,width:90}} type="number" min="1" max="14" value={days} onChange={e=>setDays(e.target.value)} /></div>
    {!status.enabled ? <button className={k?.btn} style={btn} disabled={busy} onClick={enable}>Enable</button> : <>
      <div style={row}><button className={k?.btn} style={btn} disabled={busy} onClick={()=>act('post','/superadmin/demo/seed')}>Seed demo data</button><button style={btn} disabled={busy} onClick={reset}>Reset demo</button><button style={btn} disabled={busy} onClick={extend}>Extend</button><button style={dangerBtn} disabled={busy} onClick={disable}>Disable</button></div>
      <div style={{marginTop:10}}><b style={{fontSize:12}}>Jump to phase</b><div style={row}>{PHASES.map(p=><button key={p} style={small} disabled={busy} onClick={()=>act('post','/superadmin/demo/phase',{phase:p})}>{p}</button>)}</div></div>
      <div style={{marginTop:10,fontSize:12,opacity:.75}}>Demo voters: {status.counts?.voters || 0} · Applications: {status.counts?.applications || 0} · Candidates: {status.counts?.candidates || 0} · Inbox: {status.counts?.inbox || 0}</div>
      {Object.keys(status.credentials || {}).length > 0 && <details style={{marginTop:10}}><summary>Demo credentials</summary><pre style={pre}>{JSON.stringify(status.credentials,null,2)}</pre></details>}
    </>}
    {msg && <div role="status" style={{marginTop:10,fontSize:12}}>{msg}</div>}
  </div>;
}
const box={padding:16,border:'1px solid var(--border-color)',borderRadius:12,background:'var(--card-bg)',marginBottom:16};
const notice={padding:'8px 10px',borderRadius:8,border:'1px solid var(--border-color)',fontSize:12,marginBottom:10};
const inp={padding:'9px 10px',borderRadius:8,border:'1px solid var(--border-color)',background:'var(--bg-color)',color:'var(--text-color)',fontSize:13,width:'100%',boxSizing:'border-box'};
const grid={display:'grid',gridTemplateColumns:'1fr auto',gap:8}; const row={display:'flex',gap:7,flexWrap:'wrap',marginTop:8};
const btn={padding:'8px 12px',border:0,borderRadius:7,background:'var(--success)',color:'white',fontWeight:700,cursor:'pointer',fontSize:12};
const dangerBtn={...btn,background:'var(--danger)'}; const small={...btn,background:'transparent',color:'var(--text-color)',border:'1px solid var(--border-color)'}; const pre={fontSize:10,whiteSpace:'pre-wrap',maxHeight:260,overflow:'auto'};
