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
  if (['disabled', 'unconfigured'].includes(s)) return 'Not configured';
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

const STATUS_WORDS_NEUTRAL = new Set(['unconfigured', 'disabled', 'not run', 'never', 'unknown']);
const humanKey = (k) => String(k).replaceAll('_', ' ');
const detailCell = (v) => {
  if (v == null || v === '') return '—';
  if (typeof v === 'string' && (statusOf(v) !== 'neutral' || STATUS_WORDS_NEUTRAL.has(v.toLowerCase()))) return statusLabel(v);
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
};

// Readable detail for a check: strings stay text, string lists become chips, objects become label/value rows.
// Raw JSON used to be dumped here and ran off the right edge of a phone.
export function DetailLines({ detail, caption }) {
  if (detail == null || detail === '') return null;
  let body;
  if (Array.isArray(detail)) {
    if (!detail.length) return null;
    body = <ul className="perf-chips">{detail.map((v, i) => <li key={`${typeof v === 'string' ? v : i}-${i}`}>{typeof v === 'string' ? v : JSON.stringify(v)}</li>)}</ul>;
  } else if (typeof detail === 'object') {
    const entries = Object.entries(detail);
    if (!entries.length) return null;
    body = <dl className="perf-kv">{entries.map(([k, v]) => <React.Fragment key={k}>
      <dt>{humanKey(k)}</dt><dd data-status={typeof v === 'string' ? statusOf(v) : 'neutral'}>{detailCell(v)}</dd>
    </React.Fragment>)}</dl>;
  } else {
    body = <p className="perf-detail">{String(detail)}</p>;
  }
  return <div className="perf-detailwrap">{caption ? <span className="perf-detail-caption">{caption}</span> : null}{body}</div>;
}

// One vertical checklist for both templates: blocked items first, status word beside the name (never colour
// alone), details wrapped inside the card. Shared by the migration readiness list and the safety guards.
export function ChecklistRows({ items = [], okLabel = 'Passed', badLabel = 'Blocked', captions = {}, empty }) {
  if (!items.length) return empty ? <p style={muted}>{empty}</p> : null;
  const passing = items.filter((i) => i.ok).length;
  const ordered = [...items].sort((a, b) => Number(!!a.ok) - Number(!!b.ok));
  return <div>
    <p className="perf-checksummary" role="status">{passing} of {items.length} checks passing</p>
    <ul className="perf-checklist">
      {ordered.map((item) => <li key={item.name} className="perf-checkrow">
        <span aria-hidden="true" className="perf-checkicon" data-ok={item.ok ? 'true' : 'false'}>{item.ok ? '✓' : '!'}</span>
        <div className="perf-checkbody">
          <div className="perf-checkhead">
            <strong className="perf-checkname">{item.name}</strong>
            <BackupPill state={item.ok ? 'passed' : 'failed'}>{item.ok ? okLabel : badLabel}</BackupPill>
          </div>
          <DetailLines detail={item.detail} caption={captions[item.name]} />
        </div>
      </li>)}
    </ul>
  </div>;
}

export function GuardRows({ guards = [] }) {
  if (!guards.length) return <p style={muted}>Guard checks have not run yet.</p>;
  return <ChecklistRows items={guards} okLabel="Passed" badLabel="Failed" />;
}

export function TinyList({ items = [], empty = 'No entries yet.', labelKey = 'name', detailKey = 'detail' }) {
  if (!items.length) return <p style={muted}>{empty}</p>;
  return <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
    {items.map((x, i) => <li key={x.id || x.run_id || x[labelKey] || i} style={{ fontSize: 13, overflowWrap: 'anywhere' }}>
      <strong>{x[labelKey] || x.name || x.collection || x.tenant || `Item ${i + 1}`}</strong>{x[detailKey] ? ` — ${typeof x[detailKey] === 'string' ? x[detailKey] : JSON.stringify(x[detailKey])}` : ''}
    </li>)}
  </ul>;
}
