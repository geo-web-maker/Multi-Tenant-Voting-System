import React from 'react';
import api, { getErrorMessage } from '../api';
import { useRevealReady } from './RevealGroup';

/**
 * Superadmin switch: lets IT admins add already-paid voters without a reason, proof of payment or
 * Financial Controller approval. Off by default. Every change needs a reason and is audit-logged.
 */
export default function UploadBypassPanel() {
  const [enabled, setEnabled] = React.useState(null);
  const [reason, setReason] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState({ kind: '', text: '' });
  const [settled, setSettled] = React.useState(false);

  React.useEffect(() => {
    api.get('/admin/upload-bypass').then(res => setEnabled(!!res.data.enabled))
      .catch(() => setMsg({ kind: 'error', text: 'Could not load the current setting.' }))
      .finally(() => setSettled(true));
  }, []);
  useRevealReady(settled);

  const flip = async () => {
    const next = !enabled;
    setBusy(true); setMsg({ kind: '', text: '' });
    try {
      const res = await api.put('/superadmin/upload-bypass', { enabled: next, reason: reason.trim() });
      setEnabled(!!res.data.enabled); setReason('');
      setMsg({ kind: 'ok', text: next ? 'Bypass is ON. IT admins can now add voters directly.' : 'Bypass is OFF. Normal approval rules apply.' });
    } catch (e) {
      setMsg({ kind: 'error', text: getErrorMessage(e, 'Could not change the setting.') });
    } finally { setBusy(false); }
  };

  const canFlip = enabled !== null && reason.trim().length >= 3 && !busy;

  return (
    <div style={box}>
      <h4 style={{ margin: '0 0 4px', color: 'var(--text-color)' }}>
        Voter upload bypass: {enabled === null ? '…' : enabled ? 'ON' : 'OFF'}
      </h4>
      <p style={{ margin: '0 0 12px', fontSize: 12, opacity: 0.65 }}>
        When ON, IT admins add voters directly: no reason, proof of payment or Financial Controller approval needed.
        Each addition is still audit-logged. Switch it OFF when you are done.
      </p>
      <input style={{ ...inp, width: '100%', boxSizing: 'border-box' }} placeholder="Reason for this change (kept in the audit log)"
        aria-label="Reason for change" value={reason} onChange={e => setReason(e.target.value)} maxLength={300} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
        <button style={{ ...btn, background: enabled ? 'var(--bp-no, #e74c3c)' : 'var(--bp-ok, #2ecc71)', opacity: canFlip ? 1 : 0.5 }} disabled={!canFlip} onClick={flip}>
          {busy ? 'Saving…' : enabled ? 'Turn bypass OFF' : 'Turn bypass ON'}
        </button>
        {msg.text && <span role="status" style={{ fontSize: 12, color: msg.kind === 'error' ? 'var(--bp-no, #e74c3c)' : 'var(--success)' }}>{msg.text}</span>}
      </div>
    </div>
  );
}

const box = { padding: 16, border: '1px solid var(--border-color)', borderRadius: 12, backgroundColor: 'var(--card-bg)', marginBottom: 16 };
const inp = { padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', fontSize: 14 };
const btn = { padding: '10px 16px', color: 'var(--bp-ai, #fff)', border: 'none', borderRadius: 8, fontWeight: 700, cursor: 'pointer' };
