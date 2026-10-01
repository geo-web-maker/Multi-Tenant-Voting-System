import React, { useEffect, useState } from 'react';
import { derivePhase, formatCountdown } from '../phase';
import { parseUtc } from '../tz';

// One prominent notice on the voter card. Informational only: the login form below is untouched and
// the server stays the authority (exception grants can still let a specific student through).
const THEME = {
  apply_open:    { bg: '#e8f1ff', fg: '#0b3d91', border: '#b6d0ff' },
  voting_soon:   { bg: '#fff3cd', fg: '#664d03', border: '#ffe08a' },
  voting_open:   { bg: '#e6f6ec', fg: '#0f5132', border: '#a7dbbd' },
  voting_closed: { bg: '#f1f3f5', fg: '#343a40', border: '#ced4da' },
};

function copy(state, d) {
  switch (state) {
    case 'apply_open':
      return {
        title: 'Applications are open',
        detail: d.applicationsCloseAt ? `Close ${d.applicationsCloseAt}.` : null,
        extra: d.votingOpensAt ? `Voting opens ${d.votingOpensAt}.` : 'Voting has not started yet.',
      };
    case 'voting_soon':
      return { title: 'Voting has not started yet', detail: d.votingOpensAt ? `It opens ${d.votingOpensAt}.` : null };
    case 'voting_open':
      return { title: 'Voting is open', detail: d.votingClosesAt ? `It closes ${d.votingClosesAt}.` : null };
    default:
      return { title: 'Voting is closed', detail: d.votingClosesAt ? `It closed ${d.votingClosesAt}.` : null };
  }
}

export default function PhaseBanner({ status, onApply, style }) {
  const info = derivePhase(status);
  const target = info?.countdownTo ? parseUtc(info.countdownTo) : null;
  const targetMs = target ? target.getTime() : null;
  const [now, setNow] = useState(() => Date.now());

  // One-second clock, only while there is a next phase to count down to.
  useEffect(() => {
    if (targetMs == null) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [targetMs]);

  if (!info) return null;
  const { state, dates } = info;
  const t = THEME[state];
  const c = copy(state, dates);
  const left = targetMs != null ? formatCountdown(targetMs - now) : null;

  return (
    <div
      role="status"
      data-phase={state}
      style={{
        background: t.bg, color: t.fg, border: `1px solid ${t.border}`, borderRadius: 8,
        padding: '10px 12px', marginBottom: 14, fontSize: 16, lineHeight: 1.35, ...style,
      }}
    >
      {/* The title is a <div>, not a <span>: index.css has a global rule (@media screen) that forces the theme text colour
          on every h1/h2/p/span with !important, which no inline style can beat. That left light text on this
          light-blue box. */}
      <div style={{ textAlign: 'center', color: t.fg, fontSize: 19, fontWeight: 800, lineHeight: 1.25 }}>
        {c.title}
      </div>
      {(c.detail || c.extra) && (
        <div style={{ marginTop: 6, color: t.fg }}>{[c.detail, c.extra].filter(Boolean).join(' ')}</div>
      )}
      {left && (
        <div style={{ marginTop: 6, color: t.fg, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
          Voting opens in {left}
        </div>
      )}
      {state === 'apply_open' && (
        <button
          type="button"
          data-track="phase-apply-now"
          onClick={onApply}
          style={{
            marginTop: 12, width: '100%', minHeight: 44, fontSize: 16, fontWeight: 700, border: 'none',
            borderRadius: 6, background: t.fg, color: '#fff', cursor: 'pointer',
          }}
        >
          Apply now
        </button>
      )}
    </div>
  );
}
