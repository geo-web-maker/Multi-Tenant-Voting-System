import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm, usePrompt } from './UIFeedback';
import { Icon } from './icons.jsx';
import { listContactChanges, decideContactChange, undoDigestEntry, CHANGE_LABELS, EVENT_LABELS, errMsg } from '../studentEdit';
import { ScrollList } from './UIFeedback';

const fmt = (t) => (t ? new Date(String(t).endsWith('Z') ? t : t + 'Z').toLocaleString() : '—');

/**
 * Commission: pending queue with Approve / Deny (any ONE commissioner decides) + the pre-freeze digest.
 * Overseer / SuperAdmin (readOnly): read-only list of the requests (no decide buttons) — but the
 * digest is always loaded, and SuperAdmin / Chief / Deputy Chief also get an Undo control on it
 * (gated server-side by role, independent of this prop).
 */
export default function ContactChangesQueue({ readOnly = false }) {
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();
  const [data, setData] = useState(null);
  const [digest, setDigest] = useState(null);
  const [filter, setFilter] = useState(readOnly ? 'all' : 'pending');
  const [ack, setAck] = useState({});
  const [busy, setBusy] = useState('');
  const [undoBusy, setUndoBusy] = useState('');

  const loadDigest = useCallback(() => {
    api.get('/admin/contact-changes/digest').then(r => setDigest(r.data)).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try { setData(await listContactChanges()); } catch (e) { toast(errMsg(e, 'Could not load contact changes.'), { kind: 'error' }); }
  }, [toast]);
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  useEffect(() => { loadDigest(); }, [loadDigest]);
  if (!data) return <p style={{ opacity: 0.6 }}>Loading…</p>;

  const decide = async (c, decision) => {
    let note = '';
    if (decision === 'deny') {
      note = (await prompt('Why are you denying this request? (required)', { placeholder: 'Reason' })) || '';
      if (note.trim().length < 3) { toast('A denial needs a note.', { kind: 'error' }); return; }
    } else {
      if (c.warnings.length && !ack[c.id]) { toast('Tick “I have checked” to acknowledge the warnings first.', { kind: 'error' }); return; }
      if (!(await confirm(`Approve? Your name is recorded, it takes effect immediately, the voter's current code is cancelled and a notice SMS goes to the old number.`, { confirmText: 'Approve' }))) return;
    }
    setBusy(c.id);
    try {
      await decideContactChange(c.id, { decision, note, acknowledge_warnings: Boolean(ack[c.id]) });
      toast(decision === 'approve' ? 'Approved and applied.' : 'Denied.', { kind: 'success' });
      load();
    } catch (e) { toast(errMsg(e, 'Could not record the decision.'), { kind: 'error' }); load(); }
    finally { setBusy(''); }
  };

  const undoEntry = async (entry) => {
    const reason = (await prompt(
      `Undo this ${EVENT_LABELS[entry.event] || entry.event.replace(/_/g, ' ')} for ${entry.student_id}? This applies immediately. Why are you undoing it? (required, 10+ characters)`,
      { placeholder: 'Reason for undoing this change' }
    )) || '';
    if (reason.trim().length < 10) { toast('Undoing a change needs a written reason (10+ characters).', { kind: 'error' }); return; }
    if (!(await confirm('Reverse this change now? This is recorded against your name.', { confirmText: 'Undo change' }))) return;
    setUndoBusy(entry.id);
    try {
      await undoDigestEntry(entry.id, reason.trim());
      toast('Change undone.', { kind: 'success' });
      loadDigest();
    } catch (e) { toast(errMsg(e, 'Could not undo this change.'), { kind: 'error' }); }
    finally { setUndoBusy(''); }
  };

  const items = filter === 'all' ? data.items : data.items.filter(c => c.status === filter);

  return (
    <div>
      {!readOnly && data.roster && data.roster.phase === 'pre_freeze' && <div style={{ ...box, marginBottom: 12 }}>The roster is not frozen yet — IT admins still edit directly. Requests appear here from the freeze onward.</div>}
      <div style={{ display: 'flex', gap: 8, margin: '12px 0', flexWrap: 'wrap' }}>
        {['pending', 'approved', 'denied', 'expired', 'all'].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{ ...ghost, ...(filter === f && { borderColor: 'var(--success)', color: 'var(--success)' }) }}>
            {f} ({f === 'all' ? data.items.length : data.items.filter(c => c.status === f).length})
          </button>
        ))}
      </div>

      {items.length === 0 && <p style={{ opacity: 0.55 }}>No {filter === 'all' ? '' : filter} contact changes.</p>}
      <ScrollList>
      {items.map(c => (
        <div key={c.id} style={{ ...box, marginBottom: 10, borderColor: c.breakglass ? 'var(--danger)' : undefined }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <b style={{ fontSize: 14 }}>{CHANGE_LABELS[c.change_type]} — {c.full_name} <code style={{ fontSize: 11 }}>{c.student_id}</code></b>
            <span style={{ fontSize: 11, fontWeight: 700 }}>{c.status.toUpperCase()}{c.breakglass ? ' · BREAK-GLASS' : ''}</span>
          </div>
          <p style={muted}>
            {c.old_masked && <>Old: <code>{c.old_masked}</code> → </>}New: <b><code>{c.new_value || '—'}</code></b>
            {c.otp_in_progress && <> · voter has a code in progress</>}
          </p>
          <p style={muted}>
            Requested by <b>{c.requested_by}</b> · {fmt(c.requested_at)} · evidence: {c.evidence_type.replace(/_/g, ' ')}
            {c.evidence_note && <> — “{c.evidence_note}”</>}
          </p>
          {c.decided_by && <p style={muted}>Decided by <b>{c.decided_by}</b> · {fmt(c.decided_at)}{c.decision_note && <> — {c.decision_note}</>}{c.status === 'approved' && c.notice_status === 'failed' && <> · <b style={{ color: 'var(--danger)' }}>notice to old number failed (follow up)</b></>}</p>}
          {c.warnings.map(w => <Flag key={w.code}>{w.message}</Flag>)}
          {c.status === 'pending' && !readOnly && (
            <>
              {c.warnings.length > 0 && (
                <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', margin: '6px 0' }}>
                  <input type="checkbox" checked={Boolean(ack[c.id])} onChange={e => setAck({ ...ack, [c.id]: e.target.checked })} /> I have checked
                </label>)}
              <p style={muted}>If the old number is still reachable, phone it and ask whether the voter asked for this. A “no” means deny and escalate. Expires {fmt(c.expires_at)}.</p>
              <div style={{ display: 'flex', gap: 8 }}>
                <button disabled={busy === c.id} style={{ ...btn, background: '#2ecc71', flex: 1 }} onClick={() => decide(c, 'approve')}>Approve</button>
                <button disabled={busy === c.id} style={{ ...btn, background: '#e74c3c', flex: 1 }} onClick={() => decide(c, 'deny')}>Deny</button>
              </div>
            </>
          )}
        </div>
      ))}
      </ScrollList>

      {digest && (
        <details style={{ ...box, marginTop: 16 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>
            Pre-freeze digest: every direct contact edit an IT admin has made{digest.freeze_at ? <> before {fmt(digest.freeze_at)}</> : <> so far</>} ({digest.entries.length})
          </summary>
          <p style={muted}>Covers the full history, not just a recent window — an IT admin can edit a voter at any point before the freeze.</p>
          {digest.entries.length === 0 ? <p style={muted}>No direct contact edits recorded.</p> : (
            <div style={{ overflow: 'auto', maxHeight: '45vh' }}>
              <table style={{ width: '100%', minWidth: digest.can_undo ? '760px' : '640px', fontSize: 12, borderCollapse: 'collapse', marginTop: 8, tableLayout: 'fixed' }}>
                <thead><tr>{[['When', '11%'], ['Voter', '13%'], ['Change', '13%'], ['Old', '15%'], ['New', '15%'], ['By', '11%'], ['Reason', '12%'], ...(digest.can_undo ? [['', '10%']] : [])]
                  .map(([h, w]) => <th key={h} style={{ ...th, width: w }}>{h}</th>)}</tr></thead>
                <tbody>{digest.entries.map((e) => (
                  <tr key={e.id}>
                    <td style={td}>{fmt(e.at)}</td><td style={td}>{e.student_id}</td><td style={td}>{EVENT_LABELS[e.event] || e.event.replace(/_/g, ' ')}</td>
                    <td style={td}>{e.old || '—'}</td><td style={td}>{e.new || '—'}</td><td style={td}>{e.actor}</td><td style={td}>{e.reason}</td>
                    {digest.can_undo && (
                      <td style={td}>
                        {e.undone_at ? (
                          <span style={{ opacity: 0.6 }} title={`Undone by ${e.undone_by || '—'} · ${fmt(e.undone_at)} — ${e.undo_reason || ''}`}>Undone</span>
                        ) : e.can_undo ? (
                          <button disabled={undoBusy === e.id} style={{ ...ghost, padding: '4px 8px', fontSize: 11, borderColor: 'var(--danger)', color: 'var(--danger)' }} onClick={() => undoEntry(e)}>Undo</button>
                        ) : null}
                      </td>
                    )}
                  </tr>))}</tbody>
              </table>
            </div>)}
        </details>
      )}
    </div>
  );
}

const Flag = ({ children }) => (
  <p style={{ margin: '6px 0', padding: '6px 10px', borderRadius: 8, fontSize: 12, background: 'rgba(230,126,34,0.12)', border: '1px solid #e67e22' }}>
    <Icon name="warning" /> {children}</p>
);
const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 14, background: 'var(--card-bg)' };
const muted = { fontSize: 12, opacity: 0.75, margin: '4px 0' };
const ghost = { padding: '6px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-color)', cursor: 'pointer', fontSize: 12 };
const btn = { padding: '10px 14px', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 'bold', fontSize: 13 };
const th = { textAlign: 'left', padding: 6, borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' };
const td = { padding: 6, borderBottom: '1px solid var(--border-color)' };
