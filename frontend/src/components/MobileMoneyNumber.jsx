import React from 'react';
import { momoDisplay, momoLocalDigits } from '../paymentInfo';

/** Shows the Mobile Money number applicants pay to and the name it is registered under, with a Copy button.
 *  Renders nothing until the superadmin has set them (see ../paymentInfo.js). */

export default function MobileMoneyNumber({ info, style }) {
  const [copied, setCopied] = React.useState(false);
  if (!info?.number) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(momoLocalDigits(info.number));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard blocked: the number is on screen to type */ }
  };

  return (
    <div role="group" aria-label="Mobile Money payment details" style={{ ...box, ...style }}>
      <div style={{ fontSize: 12, opacity: 0.75 }}>Pay by Mobile Money to</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', margin: '2px 0' }}>
        <strong translate="no" style={{ fontSize: 20, letterSpacing: '0.02em', color: 'var(--text-color)' }}>{momoDisplay(info.number)}</strong>
        {navigator.clipboard && (
          <button type="button" onClick={copy} style={copyBtn}>{copied ? 'Copied' : 'Copy'}</button>
        )}
      </div>
      <div style={{ fontSize: 13 }}>Registered name: <strong>{info.name}</strong></div>
    </div>
  );
}

const box = { padding: '10px 14px', borderRadius: 10, border: '1px solid var(--border-color)', background: 'var(--card-bg)' };
const copyBtn = { padding: '3px 10px', borderRadius: 6, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', fontSize: 12, cursor: 'pointer' };
