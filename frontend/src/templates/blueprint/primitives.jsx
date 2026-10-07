// Small presentation pieces shared by the blueprint components. No state, no data fetching.

import { initials, STATUS_LABELS, statusTone } from './labels.js';
import { Icon } from '../../components/icons.jsx';

/** Accent stamp with a dashed registration frame (CSS). Logo image contained inside it when there is one (D6). */
export function Stamp({ name, logoUrl, invert = false, className = '' }) {
  return (
    <i className={`bp-logo${logoUrl ? ' bp-img' : ''}${className ? ` ${className}` : ''}`} aria-hidden="true">
      {logoUrl
        ? <img src={logoUrl} alt="" style={invert ? { filter: 'invert(1) hue-rotate(180deg)' } : undefined} />
        : initials(name)}
    </i>
  );
}

/** "● Voting Open" cell. Renders nothing while the phase is unknown. */
export function StatusCell({ phase }) {
  const label = STATUS_LABELS[phase];
  if (!label) return null;
  return (
    <div className="bp-cell bp-status">
      <small>Status</small>
      <b><i className={`bp-dot${phase === 'voting_open' ? ' bp-ok' : ''}`} />{label}</b>
    </div>
  );
}

/** "01 / 03" sheet-index cell (D5). */
export function SheetCell({ n, of }) {
  const p = (v) => String(v).padStart(2, '0');
  return (
    <div className="bp-cell bp-sheet">
      <small>Sheet</small>
      <b>{p(n)} / {p(of)}</b>
    </div>
  );
}

/** Public-page column (520 px; `wide` = 720 for results). The default UI never renders this (App hands the node back as-is). */
export function PublicWrap({ wide = false, children }) {
  return <div className={`bp-wrap${wide ? ' bp-wide' : ''}`}>{children}</div>;
}

/** Real <label> for fields that only had a placeholder (wording reused from the placeholder). */
export function FieldLabel({ htmlFor, children }) {
  return <label className="bp-lbl" htmlFor={htmlFor}>{children}</label>;
}

/** Decorative segmented progress bar (aria-hidden). `step` of `of` segments filled. */
export function StepBar({ step, of }) {
  return (
    <div className="bp-steps" aria-hidden="true">
      {Array.from({ length: of }, (_, i) => <i key={i} className={i < step ? 'bp-on' : undefined} />)}
    </div>
  );
}

/** 48 px round avatar: photo when there is one, otherwise up to two initials. */
export function Avatar({ name, src }) {
  return (
    <i className="bp-av" aria-hidden="true">
      {src ? <img src={src} alt="" /> : initials(name).slice(0, 2)}
    </i>
  );
}

const TONE = { ok: '', warn: ' bp-warn', neg: ' bp-neg', mute: ' bp-mute' };

/** Status pill: ink text on a 10% tint (ok / warn / neg / mute). */
export function Pill({ tone = 'ok', children }) {
  return <span className={`bp-pill${TONE[tone] ?? ''}`}>{children}</span>;
}

/** Pill whose tone comes from the shared status map (statusTone). `tone` overrides it; `style` is for call-site spacing only. */
export function StatusPill({ status, tone, style, children }) {
  return <span className={`bp-pill${TONE[tone ?? statusTone(status)] ?? ''}`} style={style}>{children}</span>;
}

/** Big-number card with a status pill above it (results banner). */
export function Stat({ pill, tone, value, note }) {
  return (
    <div className="bp-card bp-stat">
      <Pill tone={tone}>{pill}</Pill>
      <div className="bp-big">{value}</div>
      <div className="bp-mu">{note}</div>
    </div>
  );
}

/** One result row: caller passes the label rows as children; the bar width is the percentage. Keeps the `cand-row` hook. */
export function Meter({ pct, accent, children }) {
  return (
    <div className={`cand-row bp-meter${accent ? ' bp-warn' : ''}`}>
      {children}
      <div className="bp-bar" aria-hidden="true"><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

/** Round selection marker for option rows (apply form). Same shape as the default radio dot: it has a child only when chosen. */
export function Tick({ on }) {
  return <span className="bp-tick" aria-hidden="true">{on && <Icon name="check" />}</span>;
}
