import React from 'react';
import { fmtZoned, DEFAULT_TZ } from '../tz';
import { getTemplate } from '../template';

export const muted = { color: 'var(--text-muted)', fontSize: 13, margin: '6px 0 0' };
export const h3 = { margin: '0 0 10px', fontSize: 15 };
export const safeTime = (v) => v ? fmtZoned(v, DEFAULT_TZ) : '—';
export const bytesText = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
};
export const durationText = (s) => Number.isFinite(Number(s)) ? `${Number(s).toFixed(Number(s) < 10 ? 1 : 0)} s` : '—';
export const statusOf = (raw) => {
  const s = String(raw || '').toLowerCase();
  if (['healthy', 'ok', 'passed', 'valid', 'enabled'].includes(s)) return 'passed';
  if (['warning', 'slow', 'busy'].includes(s)) return 'warning';
  if (['critical', 'down', 'failed', 'invalid'].includes(s)) return 'failed';
  if (['running', 'queued'].includes(s)) return 'running';
  if (['skipped'].includes(s)) return 'skipped';
  return 'neutral';
};
export const statusLabel = (raw) => {
  const s = String(raw || '').toLowerCase();
  if (!s || ['not run', 'never', 'unknown'].includes(s)) return 'Not run';
  if (['ok', 'healthy', 'passed', 'valid', 'enabled'].includes(s)) return 'Healthy';
  if (['warning', 'slow', 'busy'].includes(s)) return 'Warning';
  if (['critical', 'down', 'failed', 'invalid'].includes(s)) return 'Failed';
  if (['running', 'queued'].includes(s)) return s === 'queued' ? 'Queued' : 'Running';
  if (s === 'skipped') return 'Skipped';
  if (s === 'disabled') return 'Not configured';
  return String(raw).replaceAll('_', ' ');
};

// Class helpers so nested tiles and dialogs follow the active template instead of hard-coding the default card look.
export const cardClass = () => { const bp = getTemplate(); return bp ? bp.cls.card : 'perf-card card-pad'; };
// bp.cls.alt is Blueprint's red error block, so tiles must not use it: in Blueprint a plain perf-tile is styled
// by the scoped rule in blueprint.css; the standard UI keeps the bordered card look.
export const tileClass = () => (getTemplate() ? 'perf-tile' : 'perf-card card-pad perf-tile');

export function BackupCard({ title, note, children, className = '' }) {
  return <section className={`${cardClass()} ${className}`.trim()}>
    {title ? <h3 style={h3}>{title}</h3> : null}
    {note ? <p style={muted}>{note}</p> : null}
    {children}
  </section>;
}

export function BackupPill({ state, children }) {
  const bp = getTemplate();
  const s = statusOf(state);
  const label = children || statusLabel(state);
  if (bp) return <bp.Pill tone={s === 'passed' ? 'ok' : s === 'warning' ? 'warn' : s === 'failed' ? 'neg' : 'mute'}>{label}</bp.Pill>;
  const color = s === 'passed' ? 'var(--success)' : s === 'warning' ? 'var(--warning)' : s === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
  return <span style={{ display: 'inline-block', border: `1px solid ${color}`, color, borderRadius: 999, padding: '2px 9px', fontSize: 12, fontWeight: 650, lineHeight: 1.5 }}>{label}</span>;
}

export function BackupButton({ children, onClick, disabled = false, primary = false, title, type = 'button' }) {
  return <button type={type} className={`perf-btn${primary ? ' perf-btn-primary' : ''}`} onClick={onClick} disabled={disabled} title={title}>{children}</button>;
}

export function GuardRows({ guards = [] }) {
  if (!guards.length) return <p style={muted}>Guard checks have not run yet.</p>;
  return <div style={{ display: 'grid', gap: 8 }}>
    {guards.map((g) => <div key={g.name} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, minWidth: 0 }}>
      <span aria-hidden="true" style={{ fontWeight: 800, color: g.ok ? 'var(--success)' : 'var(--danger)' }}>{g.ok ? '✓' : '!'}</span>
      <span style={{ minWidth: 0, overflowWrap: 'anywhere', fontSize: 13, flex: 1 }}>{g.name}{g.detail ? <span style={{ ...muted, display: 'block' }}>{typeof g.detail === 'string' ? g.detail : JSON.stringify(g.detail)}</span> : null}</span>
      <BackupPill state={g.ok ? 'passed' : 'failed'}>{g.ok ? 'Passed' : 'Failed'}</BackupPill>
    </div>)}
  </div>;
}

export function TinyList({ items = [], empty = 'No entries yet.', labelKey = 'name', detailKey = 'detail' }) {
  if (!items.length) return <p style={muted}>{empty}</p>;
  return <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
    {items.map((x, i) => <li key={x.id || x.run_id || x[labelKey] || i} style={{ fontSize: 13, overflowWrap: 'anywhere' }}>
      <strong>{x[labelKey] || x.name || x.collection || x.tenant || `Item ${i + 1}`}</strong>{x[detailKey] ? ` — ${typeof x[detailKey] === 'string' ? x[detailKey] : JSON.stringify(x[detailKey])}` : ''}
    </li>)}
  </ul>;
}
