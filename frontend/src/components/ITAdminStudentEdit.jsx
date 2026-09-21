import React, { useState } from 'react';
import { useToast, useConfirm } from './UIFeedback';
import { Icon } from './icons.jsx';
import ContactChangePanel from './ContactChangePanel';
import useRosterStatus from '../hooks/useRosterStatus';
import {
  lookupStudents, saveStudentEdit, fetchEditHistory,
  draftFromStudent, withNewPhoneRow, computeChanges, buildPayload, EVENT_LABELS, errMsg,
} from '../studentEdit';

// Standalone IT admin screen: form on one side, live summary on the other.
// Uses the same backend endpoint and audit logic as the superadmin screen; layout is its own.
export default function ITAdminStudentEdit() {
  const toast = useToast();
  const confirm = useConfirm();
  const roster = useRosterStatus();
  const frozen = Boolean(roster?.contact_change_required);   // phone / registration number become requests
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [searched, setSearched] = useState(false);
  const [draft, setDraft] = useState(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [recent, setRecent] = useState([]);

  const changes = draft ? computeChanges(draft) : null;
  const canSave = draft && changes.hasChanges && !changes.errors.length && reason.trim().length >= 3 && !saving;

  const search = async (e) => {
    e.preventDefault();
    setError('');
    try { setResults(await lookupStudents(q)); setSearched(true); }
    catch (err) { setError(errMsg(err, 'Search failed.')); }
  };
  const loadRecent = async (sid) => {
    try { setRecent((await fetchEditHistory(sid)).slice(0, 5)); } catch { setRecent([]); }
  };
  const pick = (s) => { setDraft(draftFromStudent(s)); setReason(''); setError(''); setResults([]); setSearched(false); loadRecent(s.student_id); };
  const setPhone = (key, patch) =>
    setDraft(d => ({ ...d, phones: d.phones.map(p => (p.key === key ? { ...p, ...patch } : p)) }));

  const save = async () => {
    setError('');
    const ok = await confirm(
      `Save ${changes.rows.length} change${changes.rows.length !== 1 ? 's' : ''}? They apply immediately and are recorded in the audit log.`,
      { confirmText: 'Save changes' });
    if (!ok) return;
    setSaving(true);
    try {
      const res = await saveStudentEdit(buildPayload(draft, reason));
      toast('Student updated and recorded in the audit log.', { kind: 'success' });
      setDraft(draftFromStudent(res.student)); setReason(''); loadRecent(res.student.student_id);
    } catch (err) { setError(errMsg(err, 'Save failed.')); }
    finally { setSaving(false); }
  };

  return (
    <div className="itadmin-split">
      <div className="itadmin-card">
        <h4 style={title}>Edit Student Details</h4>
        <p style={muted}>{frozen ? 'The roster is frozen: only name typos can be corrected here (max 2 per voter). Phone and registration-number changes are submitted below for approval.' : 'Name, phone numbers and registration number can be changed here. Changes apply immediately and need a reason.'}</p>

        <form onSubmit={search} className="itadmin-row">
          <input className="itadmin-input" placeholder="Search by name or registration number" aria-label="Search students"
            value={q} onChange={e => setQ(e.target.value)} />
          <button type="submit" className="itadmin-btn ghost" disabled={q.trim().length < 2}><Icon name="search" /> Search</button>
        </form>
        {results.map(s => (
          <button key={s.student_id} type="button" className="itadmin-pick" onClick={() => pick(s)}>
            <b>{s.full_name}</b> <span style={{ opacity: 0.6, fontSize: 12 }}>{s.student_id}</span>
          </button>
        ))}
        {searched && results.length === 0 && <p style={muted}>No matching students.</p>}
        {frozen && <ContactChangePanel student={draft?.original || null} />}

        {draft && (
          <div style={{ marginTop: 16 }}>
            <label style={lbl}>Name</label>
            <input className="itadmin-input" value={draft.full_name} onChange={e => setDraft({ ...draft, full_name: e.target.value })} />
            <label style={{ ...lbl, marginTop: 10 }}>Registration number</label>
            <input className="itadmin-input" value={draft.new_student_id} disabled={draft.original.holds_admin_role || frozen}
              onChange={e => setDraft({ ...draft, new_student_id: e.target.value })} />
            {draft.original.holds_admin_role && <p style={warn}><Icon name="warning" /> This student holds an admin or commission role; the registration number cannot be changed.</p>}

            <label style={{ ...lbl, marginTop: 10 }}>Phone numbers</label>
            {draft.phones.map(p => (
              <div key={p.key} className="itadmin-row" style={{ marginTop: 6 }}>
                <input className="itadmin-input" aria-label="Phone number" value={p.value} disabled={p.removed || frozen}
                  style={{ textDecoration: p.removed ? 'line-through' : 'none' }} placeholder="e.g. 0705123456"
                  onChange={e => setPhone(p.key, { value: e.target.value })} />
                <button type="button" className="itadmin-btn ghost" disabled={frozen} aria-label={p.removed ? 'Undo remove' : 'Remove phone'}
                  onClick={() => setPhone(p.key, { removed: !p.removed })}><Icon name={p.removed ? 'refresh' : 'trash'} /></button>
              </div>
            ))}
            <button type="button" className="itadmin-btn ghost" style={{ marginTop: 8 }} disabled={frozen} onClick={() => setDraft(withNewPhoneRow(draft))}>
              <Icon name="plus" /> Add phone number
            </button>

            <label style={{ ...lbl, marginTop: 14 }}>Reason (required)</label>
            <textarea className="itadmin-input" style={{ height: 80 }} value={reason} onChange={e => setReason(e.target.value)}
              placeholder="Why is this change being made?" />
            {error && <p style={err}><Icon name="warning" /> {error}</p>}
            <button type="button" className="itadmin-btn green" style={{ marginTop: 12, opacity: canSave ? 1 : 0.5 }} disabled={!canSave} onClick={save}>
              {saving ? 'Saving…' : <><Icon name="save" /> Save changes</>}
            </button>
          </div>
        )}
      </div>

      <aside className="itadmin-card itadmin-summary" aria-label="Live summary">
        <h4 style={title}>Summary</h4>
        <div className="itadmin-kv"><span>Student</span><b>{draft ? draft.original.full_name : '—'}</b></div>
        <div className="itadmin-kv"><span>Registration no.</span><b>{draft ? draft.original.student_id : '—'}</b></div>
        <div className="itadmin-kv"><span>Reason</span><b>{reason.trim() || '—'}</b></div>
        <h5 style={{ margin: '14px 0 6px', fontSize: 12, opacity: 0.65 }}>CURRENT → NEW</h5>
        <div className="itadmin-changes">
          {(!changes || changes.rows.length === 0) && <p style={muted}>No changes yet.</p>}
          {changes?.rows.map(r => (
            <div key={r.id} className="itadmin-change">
              <span style={{ fontSize: 11, opacity: 0.6 }}>{r.label}</span>
              <span>{r.from ?? 'none'} <Icon name="next" /> <b>{r.to ?? 'none'}</b></span>
            </div>
          ))}
        </div>
        {changes?.errors.map(m => <p key={m} style={err}><Icon name="warning" /> {m}</p>)}
        {changes?.warnings.map(m => <p key={m} style={warn}><Icon name="warning" /> {m}</p>)}
        {recent.length > 0 && (
          <>
            <h5 style={{ margin: '14px 0 6px', fontSize: 12, opacity: 0.65 }}>RECENT CHANGES TO THIS STUDENT</h5>
            {recent.map(h => (
              <p key={h._id} style={{ margin: '4px 0', fontSize: 12 }}>
                {EVENT_LABELS[h.event] || h.event} · {new Date(h.at + 'Z').toLocaleDateString()} · {h.actor}
              </p>
            ))}
          </>
        )}
      </aside>
    </div>
  );
}

const title = { margin: '0 0 6px', color: 'var(--text-color)', fontSize: 15, fontWeight: 600 };
const muted = { fontSize: 12, opacity: 0.65, margin: '4px 0 12px' };
const lbl = { display: 'block', fontSize: 12, opacity: 0.65, fontWeight: 600, marginBottom: 4 };
const err = { color: 'var(--danger)', fontSize: 12, fontWeight: 600, margin: '8px 0 0' };
const warn = { color: 'var(--warning)', fontSize: 12, margin: '8px 0 0' };
