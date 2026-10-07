import React from 'react';
import api from '../api';
import { Icon } from './icons.jsx';

export default function DemoInbox() {
  const [active, setActive] = React.useState(false);
  const [messages, setMessages] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [lastSeen, setLastSeen] = React.useState(() => sessionStorage.getItem('demo_inbox_seen') || '');

  const load = React.useCallback(async () => {
    try {
      const r = await api.get('/demo/inbox');
      setActive(true); setMessages(r.data?.messages || []); return true;
    } catch (e) {
      if (e.response?.status === 404) { setActive(false); setMessages([]); return false; }
      return active;
    }
  }, [active]);

  React.useEffect(() => { let alive = true; load().then(on => { if (!alive || !on) return; }); return () => { alive = false; }; }, [load]);
  // Poll fast while demo is on; keep checking slowly while off so enabling demo shows the inbox without a reload.
  React.useEffect(() => { const id = setInterval(load, active ? 5000 : 30000); return () => clearInterval(id); }, [active, load]);

  if (!active) return null;
  const unread = messages.filter(m => !lastSeen || String(m.created_at) > lastSeen).length;
  const markSeen = () => { const latest = messages[0]?.created_at || new Date().toISOString(); setLastSeen(String(latest)); sessionStorage.setItem('demo_inbox_seen', String(latest)); setOpen(true); };
  const copyCode = async code => { try { await navigator.clipboard.writeText(code); } catch { /* browser may deny clipboard */ } };
  return (
    <>
      <div style={banner} role="status">DEMO: no real SMS sent</div>
      {open && <div style={panel} role="dialog" aria-label="Demo SMS inbox">
        <div style={head}><strong>Demo message inbox</strong><button onClick={() => setOpen(false)} aria-label="Close demo inbox">×</button></div>
        <div style={body}>
          {messages.length === 0 ? <p style={muted}>No messages yet.</p> : messages.map(m => {
            const code = m.kind === 'otp' ? m.message.match(/\b(\d{6})\b/)?.[1] : null;
            const url = m.message.match(/https?:\/\/\S+/)?.[0];
            return <div key={m.id} style={item}><div style={meta}>{m.kind} · {m.to}</div><div style={{ whiteSpace: 'pre-wrap' }}>{m.message}</div>{code && <button style={smallBtn} onClick={() => copyCode(code)}>Copy code</button>}{url && <a style={smallLink} href={url} target="_blank" rel="noreferrer">Open</a>}</div>;
          })}
        </div>
      </div>}
      <button onClick={markSeen} aria-label="Open demo message inbox" style={fab} className="demo-inbox-fab"><Icon name="chat" />{unread > 0 && <span style={badge}>{unread > 99 ? '99+' : unread}</span>}</button>
    </>
  );
}

const banner = { position: 'sticky', top: 0, left: 0, right: 0, zIndex: 3000, textAlign: 'center', padding: '7px 12px', background: 'var(--warning)', color: 'var(--text-color)', fontSize: 12, fontWeight: 800, boxShadow: '0 1px 5px rgba(0,0,0,.12)' };
const fab = { position: 'fixed', right: 82, bottom: 'calc(var(--bottom-bar-height,0px) + 24px)', zIndex: 2601, width: 48, height: 48, borderRadius: '50%', border: '2px solid var(--brand-accent,var(--warning))', background: 'var(--brand-primary,var(--info))', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', boxShadow: '0 4px 10px rgba(0,0,0,.18)' };
const badge = { position: 'absolute', top: -5, right: -5, minWidth: 20, height: 20, borderRadius: 10, padding: '0 5px', display: 'grid', placeItems: 'center', background: 'var(--danger)', color: 'white', fontSize: 10, fontWeight: 800 };
const panel = { position: 'fixed', right: 16, bottom: 84, width: 'min(390px,calc(100vw - 32px))', maxHeight: '65vh', zIndex: 3001, background: 'var(--card-bg)', color: 'var(--text-color)', border: '1px solid var(--border-color)', borderRadius: 12, boxShadow: '0 10px 35px rgba(0,0,0,.2)', overflow: 'hidden' };
const head = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--border-color)' };
const body = { padding: 10, overflowY: 'auto', maxHeight: '55vh' };
const item = { padding: '10px 0', borderBottom: '1px solid var(--border-color)', fontSize: 12, lineHeight: 1.5 };
const meta = { fontSize: 10, opacity: .55, marginBottom: 4, textTransform: 'uppercase' };
const muted = { opacity: .55, fontSize: 12 };
const smallBtn = { marginTop: 6, marginRight: 8, border: '1px solid var(--border-color)', borderRadius: 6, background: 'transparent', color: 'var(--text-color)', padding: '4px 7px', cursor: 'pointer', fontSize: 11 };
const smallLink = { fontSize: 11, color: 'var(--success)', fontWeight: 700 };
