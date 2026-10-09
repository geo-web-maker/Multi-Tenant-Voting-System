import React from 'react';
import { momoDisplay, momoLocalDigits } from '../paymentInfo';
import { Icon } from './icons.jsx';

/** Shows the Mobile Money number applicants pay to and the name it is registered under, with a Copy button.
 *  Renders nothing until the superadmin has set them (see ../paymentInfo.js). */

export default function MobileMoneyNumber({ info, style }) {
  const [copied, setCopied] = React.useState(false);
  if (!info?.number) return null;
  const canCopy = !!navigator.clipboard || legacyCopyAvailable();

  const copy = async () => {
    const text = momoLocalDigits(info.number);
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      ok = legacyCopy(text);   // older / restricted browsers
    }
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }   // else: the number is on screen to type
  };

  return (
    <div role="group" aria-label="Mobile Money payment details" style={{ ...box, ...style }}>
      <div style={label}>Pay by Mobile Money to</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', margin: '6px 0 10px' }}>
        <strong translate="no" style={numberText}>{momoDisplay(info.number)}</strong>
        {canCopy && (
          <button type="button" data-track="apply-copy-number" onClick={copy} aria-label="Copy payment number"
            style={{ ...copyBtn, ...(copied ? copiedBtn : null) }}>
            <Icon name={copied ? 'check' : 'copy'} />
            <span aria-live="polite">{copied ? 'Copied' : 'Copy'}</span>
          </button>
        )}
      </div>
      <div style={label}>Registered name</div>
      <div translate="no" style={nameText}>{info.name}</div>
    </div>
  );
}

function legacyCopyAvailable() {
  return typeof document !== 'undefined' && typeof document.execCommand === 'function';
}

function legacyCopy(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return !!ok;
  } catch { return false; }
}

// Colours come from the template accent (--bp-ac / --bp-ai, set from the org's branding by brandColors.js) with
// legacy fallbacks, so the same markup follows branding in the default and blueprint templates.
const ACCENT = 'var(--bp-ac, var(--brand-primary, navy))';
const ACCENT_INK = 'var(--bp-ai, var(--brand-on-primary, white))';
const box = { padding: '12px 14px', borderRadius: 10, border: '1px solid var(--border-color)', background: 'var(--card-bg)' };
const label = { fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', opacity: 0.7 };
const numberText = { fontSize: 26, lineHeight: 1.2, fontWeight: 800, letterSpacing: '0.02em', color: 'var(--text-color)', userSelect: 'all' };
const nameText = { fontSize: 18, lineHeight: 1.3, fontWeight: 800, color: 'var(--text-color)', marginTop: 2 };
const copyBtn = { display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 44, padding: '0 18px', borderRadius: 99, border: `2px solid ${ACCENT}`, background: ACCENT, color: ACCENT_INK, fontWeight: 700, fontSize: 14, cursor: 'pointer' };
const copiedBtn = { background: 'transparent', color: 'var(--text-color)' };
