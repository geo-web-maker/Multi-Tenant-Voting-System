import React from 'react';

// Small pill showing how far a staff member's first-login set-up has got.
// `state` comes from the backend `login_state` field on the IT admin / overseer lists.
const STATES = {
  active:         { label: 'Password changed',       tone: 'var(--success)', title: 'Signed in and replaced the temporary password.' },
  awaiting:       { label: 'Awaiting first login',   tone: 'var(--warning)', title: 'Credentials were sent; the temporary password has not been replaced yet.' },
  expired:        { label: 'Temp password expired',  tone: 'var(--danger)',  title: 'The temporary password lapsed before it was replaced. Use Reset Password.' },
  no_credentials: { label: 'No credentials sent',    tone: 'var(--text-color)', title: 'No credentials have been sent yet.' },
};

export default function LoginStatusBadge({ state }) {
  const s = STATES[state];
  if (!s) return null;
  return (
    <span
      title={s.title}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 6,
        padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600, lineHeight: '16px',
        color: 'var(--text-color)',
        border: `1px solid color-mix(in srgb, ${s.tone} 45%, transparent)`,
        backgroundColor: `color-mix(in srgb, ${s.tone} 12%, transparent)`,
      }}
    >
      <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: s.tone, opacity: state === 'no_credentials' ? 0.4 : 1 }} />
      {s.label}
    </span>
  );
}
