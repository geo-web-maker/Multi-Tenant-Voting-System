import React from 'react';
import useIsNarrowViewport from '../hooks/useIsNarrowViewport';
import { clockLabel, tickIndexes } from '../perfFormat';

// Responsive SVG line charts for the Performance tab. Same look as the Site Usage timeline: three gridlines,
// y labels, time labels along the bottom. Colours are tokens only, so both templates and both themes work.
// Sizes are in viewBox units: on a phone the viewBox is narrow, so the 11-unit labels stay about 11 px wide on screen.

// Distinct without relying on colour alone: colour plus dash pattern.
const LINE_STYLES = [
  { color: '--brand-primary', dash: '' }, { color: '--brand-accent', dash: '' },
  { color: '--text-color', dash: '7 4' }, { color: '--brand-primary', dash: '2 4' },
  { color: '--brand-accent', dash: '7 4' }, { color: '--text-muted', dash: '' },
];

const niceNumber = (v) => (v >= 10 ? Math.round(v) : Number(v.toFixed(v >= 1 ? 1 : 2)));

/**
 * lines: [{ name, points: number|null[] }]. `startTs` and `stepS` (epoch seconds) turn bucket positions into time labels.
 * Without them the bottom axis only shows "now". `fill` shades the area under the first line (single-series charts).
 */
export function PerfChart({ lines = [], cap = null, label, unit = '/s', range = '15m', startTs = null, stepS = null, fill = false, tz }) {
  const narrow = useIsNarrowViewport();
  const w = narrow ? 360 : 1000;
  const h = narrow ? 230 : 260;
  const pad = { l: narrow ? 34 : 40, r: 8, t: 12, b: 26 };
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const n = Math.max(0, ...lines.map((l) => l.points.length));
  const values = lines.flatMap((l) => l.points).filter((v) => v !== null && v !== undefined);
  const showCap = cap && values.length > 0;
  const max = Math.max(0.1, ...(showCap ? [cap] : []), ...values);
  const x = (i) => pad.l + (n > 1 ? (i / (n - 1)) * iw : iw / 2);
  const y = (v) => pad.t + ih - (v / max) * ih;
  const timed = Number.isFinite(startTs) && Number.isFinite(stepS) && n > 1;
  const ticks = timed ? tickIndexes(n, narrow ? 2 : 4) : [];
  const runsOf = (pts) => {
    const runs = []; let cur = [];
    pts.forEach((v, i) => {
      if (v === null || v === undefined) { if (cur.length) runs.push(cur); cur = []; } else cur.push([x(i), y(v)]);
    });
    if (cur.length) runs.push(cur);
    return runs;
  };
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={label} style={{ display: 'block', maxWidth: '100%' }}>
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} x2={w - pad.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--border-color)" strokeWidth="1" />
          <text x={pad.l - 4} y={y(max * f) + 4} textAnchor="end" fontSize="11" fill="var(--text-muted)">{niceNumber(max * f)}{f === 1 ? unit : ''}</text>
        </g>
      ))}
      {showCap ? (
        <g>
          <line x1={pad.l} x2={w - pad.r} y1={y(cap)} y2={y(cap)} stroke="var(--danger)" strokeWidth="1.5" strokeDasharray="5 4" />
          <text x={w - pad.r} y={y(cap) - 4} textAnchor="end" fontSize="11" fill="var(--danger)">cap {cap}{unit}</text>
        </g>
      ) : null}
      {lines.map((l, k) => {
        const st = LINE_STYLES[k % LINE_STYLES.length];
        return runsOf(l.points).map((r, i) => {
          const pts = r.map(([px, py]) => `${px},${py}`).join(' ');
          return (
            <g key={`${l.name}-${i}`}>
              {fill && k === 0 && r.length > 1 ? (
                <polygon points={`${r[0][0]},${pad.t + ih} ${pts} ${r[r.length - 1][0]},${pad.t + ih}`} fill={`var(${st.color})`} fillOpacity="0.12" />
              ) : null}
              <polyline fill="none" stroke={`var(${st.color})`} strokeWidth={fill ? 3 : 2.5} strokeDasharray={st.dash || undefined}
                strokeLinejoin="round" strokeLinecap="round" points={pts} />
              {r.length === 1 ? <circle cx={r[0][0]} cy={r[0][1]} r="3.5" fill={`var(${st.color})`} /> : null}
            </g>
          );
        });
      })}
      {timed ? ticks.map((i) => (
        <text key={i} x={x(i)} y={h - 8} fontSize="11" fill="var(--text-muted)"
          textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>
          {i === n - 1 && range !== '7d' ? 'now' : clockLabel(startTs + i * stepS, range, tz)}
        </text>
      )) : (
        <text x={w - pad.r} y={h - 8} fontSize="11" fill="var(--text-muted)" textAnchor="end">now</text>
      )}
    </svg>
  );
}

/** Legend row matching the chart's colour and dash for each line. */
export function ChartLegend({ items = [] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', fontSize: 12, margin: '8px 0' }}>
      {items.map((it, k) => {
        const st = LINE_STYLES[k % LINE_STYLES.length];
        return (
          <span key={it.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0, overflowWrap: 'anywhere' }}>
            <svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke={`var(${st.color})`} strokeWidth="2.5" strokeDasharray={st.dash || undefined} /></svg>
            {it.name}
          </span>
        );
      })}
    </div>
  );
}

// Back-compatible single-series entry point used by older callers and tests.
export function PerfLine({ points = [], cap = null, label, unit = '', ...rest }) {
  return <PerfChart lines={[{ name: label || 'series', points }]} cap={cap} label={label} unit={unit} fill {...rest} />;
}
