import React, { useState } from 'react';
import { buildTaggedLink, CHANNELS } from '../linkBuilder';

const CUSTOM = '__custom__';
const defaultCopy = (text) => navigator.clipboard?.writeText(text);

// D2c: builds https://<host>/?src=<tag> so each place a link is shared shows up as its own channel.
export default function LinkBuilder({ host, onCopy = defaultCopy }) {
  const [choice, setChoice] = useState(CHANNELS[0]);
  const [custom, setCustom] = useState('');
  const [copied, setCopied] = useState(false);
  const siteHost = host || (typeof window !== 'undefined' ? window.location.host : '');
  const isCustom = choice === CUSTOM;
  const result = buildTaggedLink(siteHost, isCustom ? custom : choice);
  const showError = !result.ok && (!isCustom || custom !== '');

  const copy = async () => {
    if (!result.ok) return;
    try { await onCopy(result.url); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* clipboard blocked: the link is on screen to copy by hand */ }
  };

  return (
    <div style={box} className="card-pad" data-testid="link-builder">
      <h3 style={h3}>Tagged share links</h3>
      <p style={muted}>Pick where you will share the link, then copy it. Visits through it appear under Traffic channels.</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
        <select aria-label="Channel" value={choice} onChange={(e) => { setChoice(e.target.value); setCopied(false); }} style={field}>
          {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
          <option value={CUSTOM}>custom tag…</option>
        </select>
        {isCustom && (
          <input aria-label="Custom tag" value={custom} onChange={(e) => { setCustom(e.target.value.trim()); setCopied(false); }}
            placeholder="e.g. hall-b" maxLength={40} style={field} />
        )}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
        <input aria-label="Tagged link" readOnly value={result.ok ? result.url : ''} style={{ ...field, flex: '2 1 240px' }} />
        <button type="button" onClick={copy} disabled={!result.ok} style={btn}>{copied ? 'Copied' : 'Copy link'}</button>
      </div>
      {showError && <p role="alert" style={{ ...muted, color: 'var(--danger)', marginTop: 6 }}>{result.error}</p>}
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)', minWidth: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const field = { minHeight: 44, padding: '8px 10px', border: '1px solid var(--border-color)', borderRadius: 8, background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, flex: '1 1 140px' };
const btn = { minHeight: 44, padding: '0 16px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--brand-primary)', color: 'var(--brand-on-primary, white)', fontWeight: 700, fontSize: 13, cursor: 'pointer' };
