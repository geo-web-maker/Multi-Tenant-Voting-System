import React from 'react';
import { bucketLabel } from '../chartTime';
import useIsNarrowViewport from '../hooks/useIsNarrowViewport';

// Hand-built responsive SVG charts (same approach as TurnoutSparkline). CSS variables only.
const pointMs = (t) => new Date(t.length === 10 ? `${t}T00:00:00Z` : t).getTime();

// Range covered by a timeline (markers outside it are not drawn).
function pointsRange(points) {
  if (!points.length) return null;
  const start = pointMs(points[0].t);
  const step = points.length > 1 ? pointMs(points[1].t) - start : 3600000;
  return { start, end: pointMs(points[points.length - 1].t) + step };
}

export function TimelineChart({ points = [], markers = [], bucket = 'day', label = 'Site usage timeline', tz = 'Africa/Kampala' }) {
  const narrow = useIsNarrowViewport();
  const w = narrow ? 360 : 1000;
  const h = narrow ? 300 : 260;
  const pad = { l: 34, r: 8, t: 10, b: 26 };
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const hasVotes = points.some((p) => (p.votes || 0) > 0);
  const max = Math.max(1, ...points.flatMap((p) => [p.views || 0, p.sessions || 0, hasVotes ? p.votes || 0 : 0]));
  const range = pointsRange(points);
  const x = (i) => pad.l + (points.length > 1 ? (i / (points.length - 1)) * iw : iw / 2);
  const y = (v) => pad.t + ih - ((v || 0) / max) * ih;
  const line = (key) => points.map((p, i) => `${x(i)},${y(p[key])}`).join(' ');
  const ticks = points.length ? [...new Set([0, 1, 2, 3, 4].map((k) => Math.round((k / 4) * (points.length - 1))))] : [];
  const fmt = (t) => bucketLabel(t, bucket, tz);
  const inRange = (m) => range && m.t >= range.start && m.t <= range.end;
  const mx = (m) => pad.l + ((m.t - range.start) / (range.end - range.start)) * iw;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={label} style={{ display: 'block', maxWidth: '100%' }}>
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} x2={w - pad.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--border-color)" strokeWidth="1" />
          <text x={pad.l - 4} y={y(max * f) + 4} textAnchor="end" fontSize="11" fill="var(--text-muted)">{Math.round(max * f)}</text>
        </g>
      ))}
      {points.length > 1 && <polyline fill="none" stroke="var(--brand-accent)" strokeWidth="2" points={line('sessions')} />}
      {points.length > 1 && hasVotes && <polyline fill="none" stroke="var(--success, #2e9e5b)" strokeWidth="2" strokeDasharray="5 3" points={line('votes')} />}
      {points.length > 1 && <polyline fill="none" stroke="var(--brand-primary)" strokeWidth="3" points={line('views')} />}
      {points.length === 1 && <circle cx={x(0)} cy={y(points[0].views)} r="4" fill="var(--brand-primary)" />}
      {markers.filter(inRange).map((m, i) => (
        <line key={i} x1={mx(m)} x2={mx(m)} y1={pad.t} y2={pad.t + ih} stroke={m.strong ? 'var(--danger)' : 'var(--text-muted)'}
          strokeWidth={m.strong ? 2 : 1} strokeDasharray="6 5" />
      ))}
      {ticks.map((i) => (
        <text key={i} x={x(i)} y={h - 8} textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'} fontSize="11" fill="var(--text-muted)">
          {fmt(points[i].t)}
        </text>
      ))}
    </svg>
  );
}

export function HourBars({ values = [], zoneLabel = 'UTC' }) {
  const max = Math.max(1, ...values);
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(24, 1fr)', gap: 3, alignItems: 'end', height: 130 }}>
        {values.map((v, i) => (
          <div key={i} title={`${String(i).padStart(2, '0')}:00 ${zoneLabel}: ${v}`}
            style={{ height: `${Math.max(3, (v / max) * 100)}%`, background: 'var(--brand-primary)', borderRadius: '3px 3px 0 0' }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', ...muted, fontSize: 12, marginTop: 4 }}>
        {[0, 6, 12, 18, 23].map((h) => <span key={h}>{String(h).padStart(2, '0')}h</span>)}
      </div>
    </div>
  );
}

export function BarRows({ items = [], empty = 'No data is available for this period.', format = (v) => v, sub }) {
  if (!items.length) return <p style={muted}>{empty}</p>;
  const max = Math.max(1, ...items.map((x) => Number(x.value) || 0));
  return (
    <div>
      {items.map((x, i) => (
        <div key={`${x.label}-${i}`} style={row}>
          <span style={{ minWidth: 0, overflowWrap: 'anywhere', flex: '1 1 40%' }}>
            {x.label}
            {sub && sub(x) ? <span style={{ ...muted, display: 'block', fontSize: 12 }}>{sub(x)}</span> : null}
          </span>
          <strong>{format(x.value)}</strong>
          <span style={{ height: 4, flex: '0 0 30%', background: 'var(--surface-2)', borderRadius: 4 }}>
            <span style={{ display: 'block', width: `${Math.min(100, ((Number(x.value) || 0) / max) * 100)}%`, height: '100%', background: 'var(--brand-accent)', borderRadius: 4 }} />
          </span>
        </div>
      ))}
    </div>
  );
}

const row = { display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--border-color)', fontSize: 13 };
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
