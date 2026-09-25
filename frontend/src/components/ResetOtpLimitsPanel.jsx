import React, { useEffect, useRef, useState } from 'react';
import api from '../api';
import { useToast, useConfirm } from './UIFeedback';
import { Icon } from './icons.jsx';
import { errMsg } from '../studentEdit';
import { regNo } from '../regNo';

// Must match RESET_REASONS in the backend.
const REASONS = [
  ['sms_delayed', 'Code was delayed or never arrived'],
  ['victim_of_lockout', 'Voter was locked out through no fault of their own'],
  ['wrong_details_fixed', 'Wrong details were corrected'],
  ['test', 'Test'],
];

const CAP_KINDS = [
  ['approver_daily', 'Contact-change approvals per day'],
  ['reset_hourly', 'OTP resets per hour'],
];

const searchVoters = (q) => api.get('/admin/otp/voter-search', { params: { q } }).then(r => r.data);
const searchAdmins = (q) => api.get('/admin/otp/admin-search', { params: { q } }).then(r => r.data);

/** Debounced "type to search" input with a results dropdown. Used for both the
 * voter field and the admin-cap field so everyone searches by name or ID
 * instead of needing to know the exact registration number / login ID. */
function TypeaheadSearch({ placeholder, ariaLabel, fetcher, onPick, renderResult }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef(null);

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); setOpen(false); setErr(''); return; }
    setLoading(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { setResults(await fetcher(q.trim())); setOpen(true); setErr(''); }
      catch (e) { setErr(errMsg(e, 'Search failed.')); setResults([]); }
      finally { setLoading(false); }
    }, 300);
    return () => clearTimeout(timer.current);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (item) => {
    onPick(item);
    setQ('');
    setResults([]);
    setOpen(false);
  };

  return (
    <div style={{ position: 'relative' }}>
      <input
        style={inp}
        placeholder={placeholder}
        aria-label={ariaLabel}
        value={q}
        onChange={e => setQ(e.target.value)}
        onFocus={() => { if (results.length > 0) setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {loading && <span style={spinnerHint}>Searching…</span>}
      {open && results.length > 0 && (
        <div style={list}>
          {results.map((item, i) => (
            <button key={i} type="button" style={listItem} onMouseDown={() => pick(item)}>
              {renderResult(item)}
            </button>
          ))}
        </div>
      )}
      {open && !loading && results.length === 0 && q.trim().length >= 2 && (
        <div style={list}><div style={{ padding: 12, fontSize: 13, opacity: 0.6 }}>No matches.</div></div>
      )}
      {err && <p style={{ color: 'var(--danger)', fontSize: 12, marginTop: 6 }}><Icon name="warning" /> {err}</p>}
    </div>
  );
}

/**
 * "Reset OTP limits" — clears one voter's send ladder and wrong-guess bucket so they can ask for a
 * fresh code. It never shows or creates a code. Every reset is logged with the reason and note, and
 * is capped per voter and per admin (set on Security & SMS).
 *
 * canOverrideCaps  — Chief / Deputy Chief Commissioner and superadmin may raise one person's cap.
 */
export default function ResetOtpLimitsPanel({ canOverrideCaps = false }) {
  const toast = useToast();
  const confirm = useConfirm();

  const [voter, setVoter] = useState(null);           // { student_id, full_name }
  const [reason, setReason] = useState('sms_delayed');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [cap, setCap] = useState({ kind: 'approver_daily', target: null, cap: '', reason: '' }); // target: { id, name, role }
  const [capBusy, setCapBusy] = useState(false);

  const canReset = voter && note.trim().length >= 3 && !busy;

  const reset = async () => {
    setError('');
    const who = voter.full_name ? `${voter.full_name} (${regNo(voter.student_id)})` : voter.student_id;
    if (!(await confirm(
      `Reset the code limits for ${who}? They will be able to request a fresh code. This is recorded against your name.`,
      { confirmText: 'Reset limits' }))) return;
    setBusy(true);
    try {
      await api.post(`/admin/voters/${encodeURIComponent(voter.student_id)}/reset-otp-limits`, { reason, note: note.trim() });
      toast('Limits reset. The voter can request a new code.', { kind: 'success' });
      setNote(''); setVoter(null);
    } catch (err) { setError(errMsg(err, 'Could not reset the limits.')); }
    finally { setBusy(false); }
  };

  const canSaveCap = cap.target && Number(cap.cap) >= 1 && cap.reason.trim().length >= 3 && !capBusy;
  const saveCap = async () => {
    const who = cap.target.name ? `${cap.target.name} (${cap.target.id})` : cap.target.id;
    if (!(await confirm(`Set the cap for ${who} to ${Number(cap.cap)}? This is recorded against your name.`,
      { confirmText: 'Save cap' }))) return;
    setCapBusy(true);
    try {
      await api.post('/admin/caps/override', {
        kind: cap.kind, admin_id: cap.target.id, cap: Number(cap.cap), reason: cap.reason.trim(),
      });
      toast('Cap updated.', { kind: 'success' });
      setCap({ ...cap, target: null, cap: '', reason: '' });
    } catch (err) { toast(errMsg(err, 'Could not update the cap.'), { kind: 'error' }); }
    finally { setCapBusy(false); }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 16, alignItems: 'start' }}>
      <div style={box}>
        <b style={{ fontSize: 15 }}>Reset a voter's code limits</b>
        <p style={muted}>
          Use this when a voter is stuck on “try again in…”. It clears their send and wrong-guess limits so they can
          ask for a new code. It never shows or creates a code.
        </p>

        {voter ? (
          <p style={{ ...muted, color: 'var(--success)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span><Icon name="check" /> Selected: {voter.full_name} ({regNo(voter.student_id)})</span>
            <button type="button" style={linkBtn} onClick={() => setVoter(null)}>Change</button>
          </p>
        ) : (
          <TypeaheadSearch
            placeholder="Search by name or registration number"
            ariaLabel="Search voters"
            fetcher={searchVoters}
            onPick={(s) => setVoter({ student_id: s.student_id, full_name: s.full_name })}
            renderResult={(s) => (<><b>{s.full_name}</b> <span style={{ opacity: 0.6, fontSize: 12 }}>{regNo(s.student_id)}</span></>)}
          />
        )}

        <select style={inp} value={reason} onChange={e => setReason(e.target.value)} aria-label="Reason">
          {REASONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <textarea style={{ ...inp, height: 64 }} value={note} onChange={e => setNote(e.target.value)}
          placeholder="Short note: what did you check? (3+ characters)" />
        {error && <p style={{ color: 'var(--danger)', fontSize: 12, fontWeight: 600 }}><Icon name="warning" /> {error}</p>}
        <button type="button" style={{ ...btn, opacity: canReset ? 1 : 0.5 }} disabled={!canReset} onClick={reset}>
          {busy ? 'Resetting…' : 'Reset limits'}
        </button>
      </div>

      {canOverrideCaps && (
        <div style={box}>
          <b style={{ fontSize: 15 }}>Raise one person's cap</b>
          <p style={muted}>
            For when a commissioner or admin has hit a daily or hourly limit and the work is legitimate. Applies to that
            person only; the organisation-wide limits stay as set on Security &amp; SMS.
          </p>
          <select style={inp} value={cap.kind} onChange={e => setCap({ ...cap, kind: e.target.value })} aria-label="Which cap">
            {CAP_KINDS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>

          {cap.target ? (
            <p style={{ ...muted, color: 'var(--success)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span><Icon name="check" /> {cap.target.name || cap.target.id} {cap.target.role ? `— ${cap.target.role}` : ''} ({cap.target.id})</span>
              <button type="button" style={linkBtn} onClick={() => setCap({ ...cap, target: null })}>Change</button>
            </p>
          ) : (
            <TypeaheadSearch
              placeholder="Search by name or login ID"
              ariaLabel="Search admins"
              fetcher={searchAdmins}
              onPick={(a) => setCap({ ...cap, target: a })}
              renderResult={(a) => (<><b>{a.name || a.id}</b> <span style={{ opacity: 0.6, fontSize: 12 }}>{a.role} · {a.id}</span></>)}
            />
          )}

          <input style={inp} type="number" min="1" max="10000" placeholder="New cap (1–10000)" value={cap.cap}
            onChange={e => setCap({ ...cap, cap: e.target.value })} />
          <input style={inp} placeholder="Reason (required, logged)" value={cap.reason}
            onChange={e => setCap({ ...cap, reason: e.target.value })} />
          <button type="button" style={{ ...btn, opacity: canSaveCap ? 1 : 0.5 }} disabled={!canSaveCap} onClick={saveCap}>
            {capBusy ? 'Saving…' : 'Save cap'}
          </button>
        </div>
      )}
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--bg-color)' };
const muted = { fontSize: 12, opacity: 0.7, margin: '4px 0 10px' };
const inp = { width: '100%', boxSizing: 'border-box', marginTop: 8, padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13 };
const btn = { marginTop: 12, padding: '10px 18px', borderRadius: 8, border: 'none', background: '#2ecc71', color: '#fff', fontWeight: 700, cursor: 'pointer', fontSize: 13 };
const linkBtn = { padding: '4px 8px', background: 'none', border: 'none', color: 'var(--accent, #2ecc71)', cursor: 'pointer', fontSize: 12, fontWeight: 600, textDecoration: 'underline' };
const list = { position: 'absolute', left: 0, right: 0, zIndex: 20, border: '1px solid var(--border-color)', borderRadius: 8, marginTop: 4, overflow: 'hidden', background: 'var(--card-bg)', boxShadow: '0 4px 14px rgba(0,0,0,0.15)' };
const listItem = { display: 'block', width: '100%', textAlign: 'left', padding: 12, background: 'var(--card-bg)', border: 'none', borderBottom: '1px solid var(--border-color)', color: 'var(--text-color)', cursor: 'pointer', fontSize: 13 };
const spinnerHint = { position: 'absolute', right: 12, top: 18, fontSize: 11, opacity: 0.5 };
