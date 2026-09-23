import React, { useState, useEffect, useRef } from 'react';
import { buildSupportLink, fmtWait } from '../supportLink';

/**
 * feedback = { message, attempts_remaining, retry_after, reason } from the last /verify-otp response.
 * There is no permanent "Access Restricted" screen any more: every lock heals by itself, so the UI
 * only shows a live countdown from the server's retry_after.
 */
export default function OtpInput({
  otp, setOtp, onVerify, onBack, phoneNumber, isSubmitting = false,
  feedback = null, supportPhone = '', orgName = '', studentId = '',
}) {
  const inputRef = useRef(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);

  // Live countdown: the server said when the lock ends (feedback.lock_until); the browser only displays it.
  useEffect(() => {
    if (!feedback?.lock_until) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [feedback]);
  const lockLeft = feedback?.lock_until ? Math.max(0, Math.ceil((feedback.lock_until - now) / 1000)) : 0;

  const locked = lockLeft > 0;
  const hasError = feedback && !locked && feedback.reason === 'wrong_code';
  const disabled = otp.length < 6 || isSubmitting || locked;
  const help = buildSupportLink(supportPhone, orgName, studentId, 'my code is not working');

  return (
    <div style={{ textAlign: 'center', color: 'var(--text-color)' }}>
      <h2 style={{ fontSize: '18px', marginBottom: '20px', fontWeight: '500' }}>
        Confirm the code sent to <span style={{ color: 'var(--success)' }}>{phoneNumber}</span>
      </h2>

      <input
        ref={inputRef} type="text" inputMode="numeric" maxLength="6" value={otp}
        placeholder="· · · · · ·" disabled={locked}
        onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
        style={{
          fontSize: '32px', width: '220px', textAlign: 'center', padding: '12px',
          backgroundColor: 'var(--surface-2)', border: hasError ? '2px solid #e74c3c' : '2px solid var(--border-color)',
          borderRadius: '12px', color: 'var(--text-color)', letterSpacing: '8px', outline: 'none', opacity: locked ? 0.5 : 1,
        }}
      />

      {locked && (
        <p role="alert" style={{ color: 'var(--danger)', fontSize: '14px', marginTop: '10px' }}>
          Too many incorrect codes. You can try again in <b>{fmtWait(lockLeft)}</b>. You do not need to do anything.
        </p>
      )}
      {hasError && (
        <p role="alert" style={{ color: 'var(--danger)', fontSize: '14px', marginTop: '10px' }}>{feedback.message}</p>
      )}
      {feedback?.reason === 'no_live_code' && (
        <p role="alert" style={{ color: 'var(--warning)', fontSize: '14px', marginTop: '10px' }}>{feedback.message}</p>
      )}

      <div style={{ marginTop: '30px', display: 'flex', gap: '15px', justifyContent: 'center' }}>
        <button onClick={onBack} style={secondaryBtnStyle}>Back</button>
        <button
          onClick={onVerify} disabled={disabled}
          style={{
            backgroundColor: disabled ? 'var(--surface-2)' : '#2ecc71', color: 'white', padding: '12px 30px',
            border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: disabled ? 'default' : 'pointer',
          }}
        >
          {isSubmitting ? 'Verifying…' : 'Verify Account'}
        </button>
      </div>

      {help && (locked || hasError) && (
        <a href={help} target="_blank" rel="noopener noreferrer"
           style={{ display: 'block', marginTop: '15px', color: 'var(--success)', fontWeight: 'bold', textDecoration: 'none' }}>
          Need help? Contact support on WhatsApp
        </a>
      )}
    </div>
  );
}

const secondaryBtnStyle = {
  padding: '12px 25px', borderRadius: '8px', border: '1px solid var(--border-color)',
  background: 'transparent', color: 'var(--text-color)', cursor: 'pointer',
};
