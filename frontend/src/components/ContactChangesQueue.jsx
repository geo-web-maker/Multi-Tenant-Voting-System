import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm, usePrompt } from './UIFeedback';
import { Icon } from './icons.jsx';
import { listContactChanges, decideContactChange, CHANGE_LABELS, errMsg } from '../studentEdit';
import { SmsUsageTile } from './SecurityPanel';

const fmt = (t) => (t ? new Date(String(t).endsWith('Z') ? t : t + 'Z').toLocaleString() : '—');

/**
 * Commission: pending queue with Approve / Deny (any ONE commissioner decides) + the pre-freeze digest.
 * Overseer (readOnly): live feed with approver names, quotas, alerts and duplicate-number flags.
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

  const load = useCallback(async () => {
    try { setData(await listContactChanges()); } catch (e) { toast(errMsg(e, 'Could not load contact changes.'), { kind: 'error' }); }
  }, [toast]);
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  useEffect(() => { api.get('/admin/contact-changes/digest').then(r => setDigest(r.data)).catch(() => {}); }, []);
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

  const items = filter === 'all' ? data.items : data.items.filter(c => c.status === filter);
  const st = data.stats;

  return (
    <div>
      {data.roster && data.roster.phase === 'pre_freeze' && <div style={{ ...box, marginBottom: 12 }}>The roster is not frozen yet — IT admins still edit directly. Requests appear here from the freeze onward.</div>}
      {readOnly && <SmsUsageTile />}
      {readOnly && st && (
        <div style={{ ...box, margin: '12px 0' }}>
          <b style={{ fontSize: 13 }}>Live signals</b>
          <p style={muted}>
            Approved {st.approved_total} of {st.electorate} voters (<b>{st.pct_of_electorate}%</b>; alert {st.limits.alert_pct}%, hard stop {st.limits.hard_cap_pct}%) · pending {st.pending_total} · notice failed {st.notice_failed}
          </p>
          {st.alerts.quota && <Flag>Contact changes above {st.limits.alert_pct}% of the electorate — ask the chief commissioner to review.</Flag>}
          {st.alerts.hard_stop && <Flag>Hard stop reached: only the chief commissioner can approve more.</Flag>}
          {st.alerts.approver_concentration && <Flag>One approver made {Math.round(st.top_approver_share * 100)}% of approvals — ask the chief commissioner to spread the load.</Flag>}
          {st.alerts.duplicate_number && <Flag>The same new number appears in several requests ({st.duplicate_new_numbers.join(', ')}) — possible redirection. Alert the chief commissioner.</Flag>}
          {st.otp_reset_alerts.length > 0 && <Flag>{st.otp_reset_alerts.length} admin “reset OTP limits” alert(s) in the last 24 h (an unusually busy account; not a block by itself).</Flag>}
          {Object.keys(st.approvals_by_approver).length > 0 && (
            <p style={muted}>Approvals by approver: {Object.entries(st.approvals_by_approver).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>)}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, margin: '12px 0', flexWrap: 'wrap' }}>
        {['pending', 'approved', 'denied', 'expired', 'all'].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{ ...ghost, borderColor: filter === f ? 'var(--success)' : undefined, color: filter === f ? 'var(--success)' : undefined }}>
            {f} ({f === 'all' ? data.items.length : data.items.filter(c => c.status === f).length})
          </button>
        ))}
      </div>

      {items.length === 0 && <p style={{ opacity: 0.55 }}>No {filter === 'all' ? '' : filter} contact changes.</p>}
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

      {digest?.freeze_at && (
        <details style={{ ...box, marginTop: 16 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>Pre-freeze digest: contact edits in the {digest.days} days before {fmt(digest.freeze_at)} ({digest.entries.length})</summary>
          {digest.entries.length === 0 ? <p style={muted}>No contact edits in that period.</p> : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', marginTop: 8 }}>
                <thead><tr>{['When', 'Voter', 'Change', 'Old', 'New', 'By', 'Reason'].map(h => <th key={h} style={th}>{h}</th>)}</tr></thead>
                <tbody>{digest.entries.map((e, i) => (
                  <tr key={i}><td style={td}>{fmt(e.at)}</td><td style={td}>{e.student_id}</td><td style={td}>{e.event.replace(/_/g, ' ')}</td>
                    <td style={td}>{e.old || '—'}</td><td style={td}>{e.new || '—'}</td><td style={td}>{e.actor}</td><td style={td}>{e.reason}</td></tr>))}</tbody>
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
const th = { textAlign: 'left', padding: 6, borderBottom: '1px solid var(--border-color)' };
const td = { padding: 6, borderBottom: '1px solid var(--border-color)' };
