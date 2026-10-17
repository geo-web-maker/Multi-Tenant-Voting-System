import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useConfirm, useToast, usePrompt, ScrollList } from './UIFeedback';
import { LoadingBlock } from './Spinner.jsx';

/** Phone numbers held by more than one voter, with statistics and suggested actions.
 *  Used in Student Changes (superadmin and IT admin) and in the By-elections tab. */

const REC_TEXT = {
  delete_voter: 'Recommended: delete this duplicate record',
  remove_contact: 'Recommended: remove this number from the voter',
  change_contact: 'Recommended: change to the voter’s own number',
  keep: 'Recommended: keep as is',
};

export default function SharedContactsPanel({ role = 'superadmin', requestedBy = 'superadmin', showStats = true }) {
  const confirm = useConfirm();
  const prompt = usePrompt();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/shared-contacts');
      setData(res.data); setError('');
    } catch (e) {
      const d = e?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Could not check shared contacts.');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const findVoter = async (sid, phoneKey) => {
    const res = await api.get('/admin/students/lookup', { params: { q: sid } });
    const v = (res.data || []).find(x => x.student_id === sid);
    const idx = v ? (v.phone_numbers || []).findIndex(n => String(n).replace(/\D/g, '') === phoneKey) : -1;
    if (!v || idx < 0) throw new Error('This voter no longer has that number. Refresh the list.');
    return { voter: v, index: idx, old: v.phone_numbers[idx] };
  };

  const run = async (key, fn, okText) => {
    setBusy(key); setError('');
    try { await fn(); toast(okText, { kind: 'success' }); await load(); }
    catch (e) {
      const d = e?.response?.data?.detail;
      if (e?.message !== 'Cancelled.') setError(typeof d === 'string' ? d : (e?.message || 'The action failed.'));
    } finally { setBusy(''); }
  };

  const editPhone = (g, v, op) => run(`${g.phone_key}:${v.student_id}:${op}`, async () => {
    const { index, old } = await findVoter(v.student_id, g.phone_key);
    const body = { student_id: v.student_id, reason: 'Shared phone number resolved before by-election', phone_ops: [] };
    if (op === 'change') {
      const number = await prompt(`New phone number for ${v.full_name} (${v.student_id}):`, { placeholder: 'e.g. 0772 000 000', confirmText: 'Change number' });
      if (!number || !number.trim()) throw new Error('Cancelled.');
      body.phone_ops = [{ op: 'change', index, expected_old: old, number: number.trim() }];
    } else {
      const ok = await confirm(`Remove the shared number from ${v.full_name}? They keep their other number.`, { title: 'Remove contact', confirmText: 'Remove number' });
      if (!ok) throw new Error('Cancelled.');
      body.phone_ops = [{ op: 'remove', index, expected_old: old }];
    }
    await api.post('/admin/students/edit', body);
  }, op === 'change' ? 'Phone number changed.' : 'Phone number removed.');

  const deleteVoter = (g, v) => run(`${g.phone_key}:${v.student_id}:del`, async () => {
    const reason = await prompt(`${role === 'it_admin' ? 'Request removal of' : 'Delete'} ${v.full_name} (${v.student_id}) from the roster? Reason (recorded):`, { placeholder: 'e.g. Duplicate record', confirmText: 'Delete voter' });
    if (!reason || reason.trim().length < 3) throw new Error('A reason is required to delete a voter.');
    if (role === 'it_admin') {
      await api.post('/it-admin/students/request-remove', { student_id: v.student_id, reason: reason.trim(), requested_by: requestedBy });
    } else {
      await api.post('/superadmin/students/remove', { student_id: v.student_id, reason: reason.trim(), requested_by: requestedBy });
    }
  }, role === 'it_admin' ? 'Removal request submitted for approval.' : 'Voter deleted.');

  const acknowledge = (g) => run(`${g.phone_key}:ack`, async () => {
    const reason = await prompt('Why is this number legitimately shared (for example a household or guardian)? At least 10 characters:', { placeholder: 'Reason', confirmText: 'Acknowledge' });
    if (!reason || reason.trim().length < 10) throw new Error('A reason of at least 10 characters is required.');
    await api.post('/admin/shared-contacts/acknowledge', { phone: g.phone_key, reason: reason.trim() });
  }, 'Recorded as an accepted shared number.');

  if (!data && !error) return <LoadingBlock text="Checking shared contacts…" />;
  const groups = data?.groups || [];
  const open = groups.filter(g => !g.acknowledged);
  return (
    <section className="perf-card card-pad" data-testid="shared-contacts">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>Shared phone numbers</h3>
      <p className="perf-lead">One phone receiving codes for several voters weakens the vote. Fix or accept each number before voting opens.</p>
      {showStats && data?.stats && (
        <div data-testid="shared-contact-stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, margin: '8px 0' }}>
          {[
            ['Shared numbers', data.stats.shared_numbers],
            ['Unresolved', data.stats.unresolved_numbers],
            ['Accepted as shared', data.stats.accepted_numbers],
            ['Voters sharing', `${data.stats.voters_sharing} (${data.stats.voters_sharing_pct}%)`],
            ['Possible duplicates', data.stats.possible_duplicates],
            ['Largest group', data.stats.largest_group],
            ['Sharing and already voted', data.stats.already_voted_sharing],
          ].map(([label, value]) => (
            <div key={label} className="perf-row" style={{ padding: 8 }}>
              <div className="perf-note">{label}</div><div className="perf-row-title">{value}</div>
            </div>
          ))}
        </div>
      )}
      {data?.roster?.frozen && <p className="perf-note">The roster is frozen, so voters cannot be deleted. Changing or removing a contact is still possible.</p>}
      {error && <p className="perf-msg" data-kind="error" role="alert">{error}</p>}
      {data && open.length === 0 && <p className="perf-note">No unresolved shared numbers.</p>}
      <ScrollList maxHeight="60vh" style={{ marginTop: 8 }}>
      <div style={{ display: 'grid', gap: 12 }}>
        {groups.map(g => (
          <article key={g.phone_key} className="perf-row" style={{ display: 'grid', gap: 8, padding: 12 }}>
            <div className="perf-row-title">{g.phone_masked} · {g.count} voters{g.possible_duplicate ? ' · possible duplicate record' : ''}</div>
            {g.acknowledged && <div className="perf-note">Accepted as shared: {g.ack_reason}</div>}
            {g.voters.map(v => (
              <div key={v.student_id} style={{ display: 'grid', gap: 4 }}>
                <div className="perf-row-text">{v.full_name} ({v.student_id}){v.has_voted ? ' · has voted' : ''}{v.holds_admin_role ? ' · holds an admin role' : ''}</div>
                <div className="perf-note">{REC_TEXT[v.recommended]}. {v.reason}</div>
                {!g.acknowledged && (
                  <div className="perf-btnbar">
                    <button type="button" className="perf-btn" disabled={!!busy} onClick={() => editPhone(g, v, 'change')}>Change contact</button>
                    {v.actions.remove_contact && <button type="button" className="perf-btn" disabled={!!busy} onClick={() => editPhone(g, v, 'remove')}>Remove contact</button>}
                    {v.actions.delete_voter && <button type="button" className="perf-btn" disabled={!!busy} onClick={() => deleteVoter(g, v)}>{role === 'it_admin' ? 'Request removal' : 'Delete voter'}</button>}
                  </div>
                )}
              </div>
            ))}
            {!g.acknowledged && (
              <div className="perf-btnbar">
                <button type="button" className="perf-btn" disabled={!!busy} onClick={() => acknowledge(g)}>Accept as shared (record reason)</button>
              </div>
            )}
          </article>
        ))}
      </div>
      </ScrollList>
    </section>
  );
}
