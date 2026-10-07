import React from 'react';
import api, { getErrorMessage } from '../api';
import { momoLocalDigits } from '../paymentInfo';
import { useRevealReady } from './RevealGroup';

/**
 * Superadmin form for the Mobile Money number + registered name that applicants are shown under the
 * nomination fees and on the proof-of-payment step. Every change needs a reason and is audit-logged.
 * Leaving both fields blank stops the payment details being shown.
 */
export default function PaymentInfoPanel() {
  const [saved, setSaved] = React.useState(null);        // what the server has: { number, name } (local-format number)
  const [number, setNumber] = React.useState('');
  const [name, setName] = React.useState('');
  const [reason, setReason] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState({ kind: '', text: '' });
  const [settled, setSettled] = React.useState(false);

  const apply = data => {
    const s = { number: momoLocalDigits(data.mobile_money_number), name: data.mobile_money_name || '' };
    setSaved(s); setNumber(s.number); setName(s.name);
  };

  React.useEffect(() => {
    api.get('/payment-info').then(res => apply(res.data))
      .catch(() => setMsg({ kind: 'error', text: 'Could not load the current payment details.' }))
      .finally(() => setSettled(true));
  }, []);
  useRevealReady(settled);

  const changed = saved && (number.trim() !== saved.number || name.trim() !== saved.name);
  const canSave = changed && reason.trim().length >= 3 && !busy;

  const save = async () => {
    setBusy(true); setMsg({ kind: '', text: '' });
    try {
      const res = await api.put('/superadmin/payment-info', {
        mobile_money_number: number.trim(), mobile_money_name: name.trim(), reason: reason.trim(),
      });
      apply(res.data); setReason('');
      setMsg({ kind: 'ok', text: res.data.mobile_money_number ? 'Saved. Applicants now see this number.' : 'Saved. Payment details are hidden from applicants.' });
    } catch (e) {
      setMsg({ kind: 'error', text: getErrorMessage(e, 'Could not save the payment details.') });
    } finally { setBusy(false); }
  };

  return (
    <div style={box}>
      <h4 style={{ margin: '0 0 4px', color: 'var(--text-color)' }}>Mobile Money payment details</h4>
      <p style={{ margin: '0 0 12px', fontSize: 12, opacity: 0.65 }}>
        Shown under the nomination fee list and under the fee amount when an applicant uploads proof of payment.
        Leave both blank to hide them.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8 }}>
        <input style={inp} type="tel" inputMode="tel" placeholder="Mobile Money number, e.g. 0772 123 456" aria-label="Mobile Money number"
          value={number} onChange={e => setNumber(e.target.value)} maxLength={40} />
        <input style={inp} placeholder="Name the number is registered under" aria-label="Registered name"
          value={name} onChange={e => setName(e.target.value)} maxLength={60} />
      </div>
      <input style={{ ...inp, width: '100%', marginTop: 8, boxSizing: 'border-box' }} placeholder="Reason for this change (kept in the audit log)"
        aria-label="Reason for change" value={reason} onChange={e => setReason(e.target.value)} maxLength={300} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
        <button style={{ ...saveBtn, opacity: canSave ? 1 : 0.5 }} disabled={!canSave} onClick={save}>{busy ? 'Saving…' : 'Save payment details'}</button>
        {msg.text && <span role="status" style={{ fontSize: 12, color: msg.kind === 'error' ? 'var(--bp-no, #e74c3c)' : 'var(--success)' }}>{msg.text}</span>}
      </div>
    </div>
  );
}

const box = { padding: 16, border: '1px solid var(--border-color)', borderRadius: 12, backgroundColor: 'var(--card-bg)', marginBottom: 16 };
const inp = { padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', fontSize: 14 };
const saveBtn = { padding: '10px 16px', background: 'var(--bp-ok, #2ecc71)', color: 'var(--bp-ai, #fff)', border: 'none', borderRadius: 8, fontWeight: 700, cursor: 'pointer' };
