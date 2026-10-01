import React from 'react';
import { momoDisplay, momoLocalDigits } from '../paymentInfo';

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
      <div style={{ fontSize: 12, opacity: 0.75 }}>Pay by Mobile Money to</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', margin: '2px 0' }}>
        {canCopy ? (
          <button type="button" data-track="apply-copy-number" onClick={copy} aria-label="Copy payment number"
            style={numberBtn}>
            <strong translate="no" style={{ fontSize: 20, letterSpacing: '0.02em' }}>{momoDisplay(info.number)}</strong>
            <span style={{ fontSize: 12, opacity: 0.75, marginLeft: 8 }}>{copied ? 'Copied' : 'Tap to copy'}</span>
          </button>
        ) : (
          <strong translate="no" style={{ fontSize: 20, letterSpacing: '0.02em', color: 'var(--text-color)' }}>{momoDisplay(info.number)}</strong>
        )}
      </div>
      <div style={{ fontSize: 13 }}>Registered name: <strong>{info.name}</strong></div>
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

const box = { padding: '10px 14px', borderRadius: 10, border: '1px solid var(--border-color)', background: 'var(--card-bg)' };
const numberBtn = { display: 'inline-flex', alignItems: 'center', minHeight: 44, padding: '4px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', cursor: 'pointer' };
