import React, { useCallback, useEffect, useState } from 'react';
import { useToast, useConfirm, ScrollList } from './UIFeedback';
import { Icon } from './icons.jsx';
import {
  submitContactChange, listContactChanges, cancelContactChange,
  EVIDENCE_TYPES, CHANGE_LABELS, errMsg,
} from '../studentEdit';

// After the roster freeze, phone / registration-number edits are REQUESTS. Shows the request form for the
// selected student (if any) and the requester's own requests with live status.
export default function ContactChangePanel({ student = null }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [mine, setMine] = useState([]);
  const [form, setForm] = useState({ change_type: 'phone_change', index: 0, new_value: '', evidence_type: 'id_card_in_person', evidence_note: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setMine((await listContactChanges()).items); } catch { /* non-critical */ }
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 20000); return () => clearInterval(id); }, [load]);
  useEffect(() => { setForm(f => ({ ...f, index: 0, new_value: '' })); setError(''); }, [student?.student_id]);

  const needsIndex = form.change_type === 'phone_change' || form.change_type === 'phone_remove';
  const needsValue = form.change_type !== 'phone_remove';
  const noteMin = form.evidence_type === 'other_documented' ? 20 : 3;
  const canSend = student && !student.has_voted && !busy && (!needsValue || form.new_value.trim()) && form.evidence_note.trim().length >= noteMin;

  const send = async () => {
    setError('');
    const ok = await confirm('Submit this contact change for commissioner approval? It does not take effect until a commissioner approves it.', { confirmText: 'Submit request' });
    if (!ok) return;
    setBusy(true);
    try {
      await submitContactChange({
        student_id: student.student_id, change_type: form.change_type,
        index: needsIndex ? Number(form.index) : undefined,
        expected_old: needsIndex ? student.phone_numbers[Number(form.index)] : undefined,
        new_value: needsValue ? form.new_value : undefined,
        evidence_type: form.evidence_type, evidence_note: form.evidence_note,
      });
      toast('Request submitted. A commissioner will decide it.', { kind: 'success' });
      setForm(f => ({ ...f, new_value: '', evidence_note: '' }));
      load();
    } catch (e) { setError(errMsg(e, 'Could not submit the request.')); }
    finally { setBusy(false); }
  };

  const cancel = async (id) => {
    if (!(await confirm('Withdraw this request?', { danger: true, confirmText: 'Withdraw' }))) return;
    try { await cancelContactChange(id); load(); } catch (e) { toast(errMsg(e, 'Could not withdraw.'), { kind: 'error' }); }
  };

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ ...box, borderColor: 'var(--warning)' }}>
        <b style={{ fontSize: 13 }}>Roster frozen — contact changes need approval</b>
        <p style={muted}>Any one commissioner can approve or deny. Never change a number because of a chat message: check the student’s ID card or an official record.</p>
        {student ? (
          student.has_voted ? <p style={{ ...muted, color: 'var(--danger)' }}>This student has already voted; details can no longer change.</p> : (
            <>
              <select style={inp} value={form.change_type} onChange={e => setForm({ ...form, change_type: e.target.value })} aria-label="Type of change">
                {Object.entries(CHANGE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              {needsIndex && (
                <select style={inp} value={form.index} onChange={e => setForm({ ...form, index: e.target.value })} aria-label="Which number">
                  {student.phone_numbers.map((p, i) => <option key={p} value={i}>{p}</option>)}
                </select>
              )}
              {needsValue && (
                <input style={inp} value={form.new_value} placeholder={form.change_type === 'registration_number_change' ? 'New registration number' : 'New number e.g. 0705123456'}
                  onChange={e => setForm({ ...form, new_value: e.target.value })} />
              )}
              <select style={inp} value={form.evidence_type} onChange={e => setForm({ ...form, evidence_type: e.target.value })} aria-label="Evidence type">
                {EVIDENCE_TYPES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <textarea style={{ ...inp, height: 64 }} value={form.evidence_note} placeholder={`What did you check? (${noteMin}+ characters)`}
                onChange={e => setForm({ ...form, evidence_note: e.target.value })} />
              {error && <p style={{ color: 'var(--danger)', fontSize: 12, fontWeight: 600 }}><Icon name="warning" /> {error}</p>}
              <button type="button" style={{ ...btn, opacity: canSend ? 1 : 0.5 }} disabled={!canSend} onClick={send}>
                {busy ? 'Submitting…' : 'Submit contact change'}
              </button>
            </>
          )
        ) : <p style={muted}>Search for a student above to submit a change.</p>}
      </div>

      <h5 style={{ margin: '16px 0 6px', fontSize: 12, opacity: 0.65 }}>MY CONTACT-CHANGE REQUESTS</h5>
      {mine.length === 0 && <p style={muted}>No requests yet.</p>}
      <ScrollList maxHeight="50vh">
      {mine.map(c => (
        <div key={c.id} style={{ ...box, marginTop: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <b style={{ fontSize: 13 }}>{CHANGE_LABELS[c.change_type]} — <code>{c.student_id}</code></b>
            <span style={{ fontSize: 11, fontWeight: 700 }}>{c.status.toUpperCase()}</span>
          </div>
          <p style={muted}>
            {c.old_masked && <>Old {c.old_masked} → </>}New {c.new_value || '—'}
            {c.decided_by && <> · decided by {c.decided_by}{c.decision_note ? `: ${c.decision_note}` : ''}</>}
            {c.status === 'pending' && c.expires_at && <> · expires {new Date(c.expires_at + 'Z').toLocaleTimeString()}</>}
            {c.status === 'approved' && c.notice_status === 'failed' && <> · notice SMS to old number failed</>}
          </p>
          {c.status === 'pending' && <button type="button" style={ghost} onClick={() => cancel(c.id)}>Withdraw</button>}
        </div>
      ))}
      </ScrollList>
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 10, padding: 12, background: 'var(--card-bg)' };
const muted = { fontSize: 12, opacity: 0.7, margin: '4px 0 8px' };
const inp = { width: '100%', boxSizing: 'border-box', marginTop: 6, padding: 10, borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--surface-2)', color: 'var(--text-color)' };
const btn = { marginTop: 10, padding: '10px 16px', borderRadius: 8, border: 'none', background: '#2ecc71', color: '#fff', fontWeight: 700, cursor: 'pointer' };
const ghost = { padding: '6px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-color)', cursor: 'pointer', fontSize: 12 };
