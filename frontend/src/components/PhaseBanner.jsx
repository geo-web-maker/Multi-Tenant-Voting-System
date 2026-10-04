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

// Each state is a title plus short, centred "label / value" rows, so dates read as a balanced
// list instead of one run-on sentence.
function copy(state, d, appsClosed) {
  switch (state) {
    case 'apply_open':
      return {
        title: 'Applications are open',
        rows: [
          d.applicationsCloseAt && ['Applications close', d.applicationsCloseAt],
          d.votingOpensAt ? ['Voting opens', d.votingOpensAt] : ['Voting', 'has not started yet'],
        ],
      };
    case 'voting_soon':
      return {
        title: appsClosed ? 'Applications are closed' : 'Voting has not started yet',
        rows: [d.votingOpensAt ? ['Voting opens', d.votingOpensAt] : ['Voting', 'has not started yet']],
      };
    case 'voting_open':
      return { title: 'Voting is open', rows: [d.votingClosesAt && ['Voting closes', d.votingClosesAt]] };
    default:
      return { title: 'Voting is closed', rows: [d.votingClosesAt && ['Voting closed', d.votingClosesAt]] };
  }
}

export default function PhaseBanner({ status, onApply, style }) {
  const [now, setNow] = useState(() => Date.now());
  const info = derivePhase(status, now);
  const target = info?.countdownTo ? parseUtc(info.countdownTo) : null;
  const targetMs = target ? target.getTime() : null;

  // One-second clock, only while there is a next milestone to count down to. When the applications
  // deadline passes, derivePhase flips the banner to "closed" and the clock re-targets voting opening.
  useEffect(() => {
    if (targetMs == null) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [targetMs]);

  if (!info) return null;
  const { state, dates, appsClosed } = info;
  const t = THEME[state];
  const c = copy(state, dates, appsClosed);
  const rows = c.rows.filter(Boolean);
  const left = targetMs != null ? formatCountdown(targetMs - now) : null;
  // Colour is set explicitly everywhere: in dark mode a global text colour was winning over the
  // banner's own, leaving light text on the light-blue box (unreadable).
  const txt = { color: t.fg, textAlign: 'center' };

  return (
    <div
      role="status"
      className="no-print"
      data-phase={state}
      style={{
        background: t.bg, color: t.fg, border: `1px solid ${t.border}`, borderRadius: 8,
        padding: '14px 14px 12px', marginBottom: 14, fontSize: 16, lineHeight: 1.35,
        display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', ...style,
      }}
    >
      <div style={{ ...txt, fontSize: 19, fontWeight: 800, lineHeight: 1.25 }}>{c.title}</div>

      {rows.length > 0 && (
        <div style={{ marginTop: 10, width: '100%', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map(([label, value]) => (
            <div key={label} style={txt}>
              <div style={{ ...txt, fontSize: 12, fontWeight: 700, letterSpacing: 0.6, textTransform: 'uppercase', opacity: 0.75 }}>{label}</div>
              <div style={{ ...txt, fontSize: 16, fontWeight: 600 }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {left && (
        <div
          style={{
            marginTop: 12, width: '100%', padding: '10px 8px', borderRadius: 6,
            background: 'rgba(255,255,255,0.55)', border: `1px solid ${t.border}`, ...txt,
          }}
        >
          <div style={{ ...txt, fontSize: 12, fontWeight: 700, letterSpacing: 0.6, textTransform: 'uppercase' }}>
            {info.countdownLabel}
          </div>
          <div style={{ ...txt, fontSize: 24, fontWeight: 800, fontVariantNumeric: 'tabular-nums', lineHeight: 1.2 }}>{left}</div>
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
