import React, { useCallback, useEffect, useState } from 'react';
import { useToast, useConfirm, ScrollList } from './UIFeedback';
import { Icon } from './icons.jsx';
import ContactChangePanel from './ContactChangePanel';
import useRosterStatus from '../hooks/useRosterStatus';
import {
  lookupStudents, fetchEditHistory, saveStudentEdit,
  draftFromStudent, withNewPhoneRow, computeChanges, buildPayload, EVENT_LABELS, errMsg,
} from '../studentEdit';
import { regNo } from '../regNo';

// Edit-student UI that lives INSIDE the superadmin "Student Changes" tab.
// Changes apply immediately (no approval, no notifications); the audit history below is the control.
export default function SuperAdminStudentEdit() {
  const toast = useToast();
  const confirm = useConfirm();
  const roster = useRosterStatus();
  const frozen = Boolean(roster?.contact_change_required);

  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [draft, setDraft] = useState(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [histQ, setHistQ] = useState('');
  const [history, setHistory] = useState([]);
  const [histLoading, setHistLoading] = useState(false);

  const loadHistory = useCallback(async (query = '') => {
    setHistLoading(true);
    try {
      setHistory(await fetchEditHistory(query));
    } catch (e) {
      toast(errMsg(e, 'Could not load the change history.'), { kind: 'error' });
    } finally {
      setHistLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadHistory(''); }, [loadHistory]);

  const search = async (e) => {
    e.preventDefault();
    setError('');
    try {
      setResults(await lookupStudents(q));
    } catch (err) {
      setError(errMsg(err, 'Search failed.'));
    }
  };

  const pick = (s) => { setDraft(draftFromStudent(s)); setReason(''); setError(''); setResults([]); };

  const changes = draft ? computeChanges(draft) : null;
  const canSave = draft && changes.hasChanges && changes.errors.length === 0 && reason.trim().length >= 3 && !saving;

  const save = async () => {
    setError('');
    const summary = changes.rows.map(r => `${r.label}: ${r.from ?? 'none'} -> ${r.to ?? 'none'}`).join('\n');
    const ok = await confirm(
      `Save ${changes.rows.length} change${changes.rows.length !== 1 ? 's' : ''} now?\n\n${summary}\n\n` +
      'This takes effect immediately and is recorded in the audit history.',
      { confirmText: 'Save changes' });
    if (!ok) return;
    setSaving(true);
    try {
      const res = await saveStudentEdit(buildPayload(draft, reason));
      toast('Student updated and recorded in the audit history.', { kind: 'success' });
      setDraft(draftFromStudent(res.student));
      setReason('');
      loadHistory(histQ);
    } catch (err) {
      setError(errMsg(err, 'Save failed.'));
    } finally {
      setSaving(false);
    }
  };

  const setPhone = (key, patch) =>
    setDraft(d => ({ ...d, phones: d.phones.map(p => (p.key === key ? { ...p, ...patch } : p)) }));

  return (
    <div style={{ ...card, marginBottom: '20px' }}>
      <h4 style={cardTitle}>Edit Student Details</h4>
      <p style={muted}>
        Change a student's name, phone numbers or registration number. Changes apply immediately, need a reason,
        and are recorded in the history below.
      </p>

      <form onSubmit={search} style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <input style={{ ...inp, flex: '1 1 220px' }} placeholder="Search by name or registration number"
          aria-label="Search students" value={q} onChange={e => setQ(e.target.value)} />
        <button type="submit" style={ghostBtn} disabled={q.trim().length < 2}>Search</button>
      </form>

      {results.length > 0 && (
        <div style={list}>
          {results.map(s => (
            <button key={s.student_id} type="button" style={listItem} onClick={() => pick(s)}>
              <b>{s.full_name}</b> <span style={{ opacity: 0.6, fontSize: '12px' }}>{regNo(s.student_id)}</span>
            </button>
          ))}
        </div>
      )}

      {frozen && <ContactChangePanel compact student={draft?.original || null} />}
      {draft && (
        <div style={{ marginTop: '16px' }}>
          <div style={fieldGrid}>
            <label style={field}>
              <span style={lbl}>Name</span>
              <input style={inp} value={draft.full_name} onChange={e => setDraft({ ...draft, full_name: e.target.value })} />
            </label>
            <label style={field}>
              <span style={lbl}>Registration number</span>
              <input style={inp} value={draft.new_student_id} disabled={frozen}
                onChange={e => setDraft({ ...draft, new_student_id: e.target.value })} />
            </label>
          </div>
          {draft.original.holds_admin_role && (
            <p style={{ ...muted, color: 'var(--warning)' }}>
              <Icon name="warning" /> This student holds an admin or commission role, so the registration number cannot be changed.
            </p>
          )}

          <span style={{ ...lbl, display: 'block', marginTop: '14px' }}>Phone numbers</span>
          {draft.phones.map(p => (
            <div key={p.key} style={{ display: 'flex', gap: '8px', marginTop: '6px', alignItems: 'center' }}>
              <input style={{ ...inp, flex: 1, textDecoration: p.removed ? 'line-through' : 'none', opacity: p.removed ? 0.5 : 1 }}
                aria-label="Phone number" value={p.value} disabled={p.removed || frozen}
                onChange={e => setPhone(p.key, { value: e.target.value })} placeholder="e.g. 0705123456" />
              <button type="button" style={ghostBtn} disabled={frozen} onClick={() => setPhone(p.key, { removed: !p.removed })}
                aria-label={p.removed ? 'Undo remove' : 'Remove phone'}>
                <Icon name={p.removed ? 'refresh' : 'trash'} />
              </button>
            </div>
          ))}
          <button type="button" style={{ ...ghostBtn, marginTop: '8px' }} disabled={frozen} onClick={() => setDraft(withNewPhoneRow(draft))}>
            Add phone number
          </button>

          <div style={review}>
            <b style={{ fontSize: '13px' }}>Review: current value next to new value</b>
            {changes.rows.length === 0 && <p style={muted}>No changes yet.</p>}
            {changes.rows.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table style={tbl}>
                  <thead><tr><th style={{ ...th, width: '24%' }}>Field</th><th style={{ ...th, width: '38%' }}>Current</th><th style={{ ...th, width: '38%' }}>New</th></tr></thead>
                  <tbody>
                    {changes.rows.map(r => (
                      <tr key={r.id}>
                        <td style={td}>{r.label}</td>
                        <td style={td}>{r.from ?? <i style={{ opacity: 0.5 }}>none</i>}</td>
                        <td style={{ ...td, fontWeight: 700 }}>{r.to ?? <i style={{ opacity: 0.5 }}>none</i>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {changes.errors.map(m => <p key={m} style={errText}><Icon name="warning" /> {m}</p>)}
            {changes.warnings.map(m => <p key={m} style={{ ...muted, color: 'var(--warning)' }}><Icon name="warning" /> {m}</p>)}
          </div>

          <label style={{ ...field, marginTop: '12px' }}>
            <span style={lbl}>Reason (required)</span>
            <textarea style={{ ...inp, height: '70px', resize: 'vertical' }} value={reason}
              onChange={e => setReason(e.target.value)} placeholder="Why is this change being made?" />
          </label>
          {error && <p style={errText}><Icon name="warning" /> {error}</p>}
          <button type="button" style={{ ...greenBtn, marginTop: '12px', opacity: canSave ? 1 : 0.5 }}
            disabled={!canSave} onClick={save}>
            {saving ? 'Saving…' : <>Save changes</>}
          </button>
        </div>
      )}

      <h4 style={{ ...cardTitle, marginTop: '28px' }}>Change history (read only)</h4>
      <form onSubmit={e => { e.preventDefault(); loadHistory(histQ); }} style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <input style={{ ...inp, flex: '1 1 220px' }} aria-label="Search history"
          placeholder="Search by old or new registration number, or name"
          value={histQ} onChange={e => setHistQ(e.target.value)} />
        <button type="submit" style={ghostBtn} disabled={histLoading}>{histLoading ? 'Searching…' : 'Search'}</button>
      </form>
      {history.length === 0 && !histLoading && <p style={muted}>No changes recorded.</p>}
      <ScrollList maxHeight="60vh">
      {history.map(h => (
        <div key={h._id} style={histCard}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
            <b style={{ fontSize: '13px' }}>{EVENT_LABELS[h.event] || h.event}</b>
            <small style={{ opacity: 0.55 }}>{new Date(h.at + 'Z').toLocaleString()}</small>
          </div>
          <p style={histLine}>
            Student: <code>{h.student_id_after}</code>
            {h.student_id_before !== h.student_id_after && <> (was <code>{h.student_id_before}</code>)</>}
          </p>
          <p style={histLine}>
            <span style={{ opacity: 0.6 }}>{h.old_value ?? 'none'}</span>
            {' '}<Icon name="next" />{' '}<b>{h.new_value ?? 'none'}</b>
          </p>
          <p style={histLine}>Reason: {h.reason}</p>
          <p style={{ ...histLine, opacity: 0.55 }}>By {h.actor} ({h.actor_role === 'it_admin' ? 'IT admin' : h.actor_role})</p>
        </div>
      ))}
      </ScrollList>
    </div>
  );
}

const card = { padding: '20px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--bg-color)' };
const cardTitle = { margin: '0 0 6px', color: 'var(--text-color)', fontSize: '15px', fontWeight: '600' };
const muted = { fontSize: '12px', opacity: 0.65, margin: '4px 0 12px' };
const lbl = { fontSize: '12px', opacity: 0.65, fontWeight: '600' };
const inp = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box', minHeight: '44px' };
const field = { display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 };
const fieldGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' };
const btn = { padding: '10px 18px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', minHeight: '44px' };
const greenBtn = { ...btn, backgroundColor: '#2ecc71' };
const ghostBtn = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', minHeight: '44px' };
const list = { border: '1px solid var(--border-color)', borderRadius: '8px', marginTop: '8px', overflow: 'hidden' };
const listItem = { display: 'block', width: '100%', textAlign: 'left', padding: '12px', background: 'var(--card-bg)', border: 'none', borderBottom: '1px solid var(--border-color)', color: 'var(--text-color)', cursor: 'pointer', fontSize: '13px', minHeight: '44px' };
const review = { marginTop: '16px', padding: '12px', border: '1px dashed var(--border-color)', borderRadius: '8px', backgroundColor: 'var(--card-bg)' };
const tbl = { width: '100%', borderCollapse: 'collapse', marginTop: '8px', fontSize: '13px', tableLayout: 'fixed' };
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', fontSize: '11px', opacity: 0.6, whiteSpace: 'nowrap' };
const td = { padding: '6px 8px', borderBottom: '1px solid var(--border-color)', wordBreak: 'break-word' };
const errText = { color: 'var(--danger)', fontSize: '12px', fontWeight: 600, margin: '8px 0 0' };
const histCard = { border: '1px solid var(--border-color)', borderRadius: '10px', padding: '12px', marginTop: '10px', backgroundColor: 'var(--card-bg)' };
const histLine = { margin: '4px 0 0', fontSize: '12px', color: 'var(--text-color)', wordBreak: 'break-word' };
