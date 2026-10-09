import React from 'react';

// Small pill showing which stage a staff member's account is at, plus when they last signed in.
// `state` comes from the backend `login_state` field on the staff lists (IT admin, commissioner,
// financial controller, overseer, vetting panel); `lastLogin` from `last_login_at`.
const STATES = {
  no_credentials: { label: 'No action: credentials not sent', tone: 'var(--text-color)', title: 'No credentials have been sent yet.' },
  awaiting:       { label: 'No action: not logged in yet',    tone: 'var(--warning)',    title: 'Credentials were sent; they have not signed in.' },
  logged_in:      { label: 'Logged in: password not changed', tone: 'var(--info)',       title: 'Signed in with the temporary password but has not replaced it yet.' },
  expired:        { label: 'Temp password expired',           tone: 'var(--danger)',     title: 'The temporary password lapsed before it was replaced. Use Reset Password.' },
  active:         { label: 'Active: password changed',        tone: 'var(--success)',    title: 'Signed in and replaced the temporary password.' },
  role_login:     { label: 'Uses their role login',           tone: 'var(--info)',       title: 'Linked panel member with no separate password; opens the panel from their own admin dashboard.' },
};

export default function LoginStatusBadge({ state, lastLogin }) {
  const s = STATES[state];
  if (!s) return null;
  return (
    <>
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
    {lastLogin && (
      <small style={{ display: 'block', opacity: 0.6, marginTop: 2 }}>
        Last login {new Date(lastLogin).toLocaleString()}
      </small>
    )}
    </>
  );
}
