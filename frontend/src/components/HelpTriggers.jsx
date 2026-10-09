import React, { useEffect, useState } from 'react';
import { useHelpMenu } from '../context/HelpMenuContext';
import { Icon } from './icons.jsx';
import { HELP_TRACK, isTextEntry } from '../helpItems';

/**
 * Floating pill button — the default Help affordance on pages that have
 * no other fixed bottom UI competing for that corner (e.g. the voter
 * login screen, results page).
 */
export function FabTrigger({ compact = false }) {
  const { open, toggle } = useHelpMenu();
  const narrow = useNarrowScreen(400);
  const typing = useTextEntryFocus();
  const iconOnly = compact || narrow;
  // Fade (and ignore taps) while a text field has focus, so the ? never sits over the keyboard or the field.
  // Stays visible while the menu is open so it can still be closed.
  const faded = typing && !open;
  return (
    <button onClick={toggle} data-track={HELP_TRACK.fab} aria-label="Help" aria-hidden={faded || undefined} tabIndex={faded ? -1 : undefined}
      style={{ ...(iconOnly ? { ...fabStyle, ...fabIconOnlyStyle } : fabStyle), ...(faded ? fabFadedStyle : null) }}>
      <span className="help-fab-label" style={fabLabelStyle}>{open ? <Icon name="close" /> : '?'}</span>
      {!iconOnly && <span className="help-fab-label" style={fabLabelStyle}>{open ? 'Close' : 'Help'}</span>}
    </button>
  );
}

// True while a text input, textarea or select has focus.
function useTextEntryFocus() {
  const [typing, setTyping] = useState(() => typeof document !== 'undefined' && isTextEntry(document.activeElement));
  useEffect(() => {
    const on = () => setTyping(isTextEntry(document.activeElement));
    const onIn = (e) => setTyping(isTextEntry(e.target));
    document.addEventListener('focusin', onIn);
    document.addEventListener('focusout', on);
    return () => { document.removeEventListener('focusin', onIn); document.removeEventListener('focusout', on); };
  }, []);
  return typing;
}

// True while the viewport is narrower than `px`. Safe where matchMedia is missing (older browsers, jsdom).
function useNarrowScreen(px) {
  const query = `(max-width: ${px - 1}px)`;
  const read = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query).matches : false);
  const [narrow, setNarrow] = useState(read);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const mq = window.matchMedia(query);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener?.('change', on);
    on();
    return () => mq.removeEventListener?.('change', on);
  }, [query]);
  return narrow;
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
      {open ? <Icon name="close" /> : '?'} Help
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
  color: 'var(--brand-on-primary, white)',
  border: '2px solid var(--brand-accent, #f1c40f)',
  borderRadius: '30px',
  cursor: 'pointer',
  fontWeight: '600',
  fontSize: '14px',
  boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
  transition: 'bottom 0.2s ease, all 0.3s ease',
};

const fabLabelStyle = { fontSize: '14px' };
const fabFadedStyle = { opacity: 0, pointerEvents: 'none' };

// Icon-only: a 48 px circle, still above the 44 px touch-target minimum.
const fabIconOnlyStyle = { width: '48px', height: '48px', padding: 0, justifyContent: 'center', right: '16px' };

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
