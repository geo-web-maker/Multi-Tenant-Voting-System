import React from 'react';
import { useHelpMenu } from '../context/HelpMenuContext';

/**
 * Floating pill button — the default Help affordance on pages that have
 * no other fixed bottom UI competing for that corner (e.g. the voter
 * login screen, results page).
 */
export function FabTrigger() {
  const { open, toggle } = useHelpMenu();
  return (
    <button onClick={toggle} style={fabStyle} aria-label="Help">
      <span className="help-fab-label" style={fabLabelStyle}>{open ? '✕' : '?'}</span>
      <span className="help-fab-label" style={fabLabelStyle}>{open ? 'Close' : 'Help'}</span>
    </button>
  );
}

/**
 * Compact icon-only trigger meant to be rendered as one of the buttons
 * inside an existing sticky footer bar (e.g. next to "Clear All" on the
 * ballot page), so Help is a native part of that toolbar rather than a
 * second floating element stacked on top of it.
 */
export function InlineHelpButton({ style }) {
  const { open, toggle } = useHelpMenu();
  return (
    <button onClick={toggle} style={{ ...inlineBtnStyle, ...style }} aria-label="Help">
      {open ? '✕' : '?'} Help
    </button>
  );
}

const fabStyle = {
  position: 'fixed',
  bottom: 'calc(var(--bottom-bar-height, 0px) + 24px)',
  right: '24px', zIndex: 2600,
  display: 'flex', alignItems: 'center', gap: '8px',
  padding: '10px 24px',
  backgroundColor: 'var(--brand-primary, #003366)',
  color: '#ffffff',
  border: '2px solid var(--brand-accent, #f1c40f)',
  borderRadius: '30px',
  cursor: 'pointer',
  fontWeight: '600',
  fontSize: '14px',
  boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
  transition: 'bottom 0.2s ease, all 0.3s ease',
};

const fabLabelStyle = { fontSize: '14px' };

const inlineBtnStyle = {
  padding: '10px 18px',
  backgroundColor: 'transparent',
  color: 'var(--text-color)',
  border: '1px solid var(--border-color)',
  borderRadius: '8px',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: '14px',
  whiteSpace: 'nowrap',
};
