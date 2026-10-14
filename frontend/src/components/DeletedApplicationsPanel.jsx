import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm, usePrompt, ScrollList } from './UIFeedback';

// Superadmin archive of soft-deleted applications. Built only from the shared panel kit (UI_TEMPLATE_MANUAL section 3),
// so it looks right in both templates with no template branch.
const errText = (e, fallback) => {
  const d = e?.response?.data?.detail;
  return typeof d === 'string' && d ? d : fallback;
};
const when = (v) => (v ? new Date(v).toLocaleString() : 'an unknown time');

export default function DeletedApplicationsPanel({ refreshKey = 0, onChanged }) {
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();
  const [rows, setRows] = useState(null);      // null while the first load is in flight
  const [loadError, setLoadError] = useState('');
  const [busyId, setBusyId] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get('/superadmin/deleted-applications');
      setRows(res.data || []);
      setLoadError('');
    } catch (e) {
      setRows((r) => r || []);
      setLoadError(errText(e, 'The deleted applications could not be loaded.'));
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  const restore = async (row) => {
    const reason = await prompt(
      `Restore the application from ${row.full_name}? It comes back as pending, so the vetting panel decides it again. Enter the reason (recorded in the audit log):`,
      { title: 'Restore application', placeholder: 'Reason', confirmText: 'Restore', minLength: 3 },
    );
    if (reason === null) return;
    setBusyId(row._id);
    try {
      const res = await api.post(`/superadmin/deleted-applications/${row._id}/restore`, { reason: reason.trim() });
      toast(res.data?.candidate_was_on_ballot
        ? 'Application restored as pending. The candidate is not on the ballot until it is approved again.'
        : 'Application restored as pending.', { kind: 'success' });
      await load();
      onChanged?.();
    } catch (e) { toast(errText(e, 'Failed to restore the application.'), { kind: 'error' }); }
    finally { setBusyId(''); }
  };

  const purge = async (row) => {
    const reason = await prompt(
      `Permanently delete the archived application from ${row.full_name}? Enter the reason (recorded in the audit log):`,
      { title: 'Delete permanently', placeholder: 'Reason', confirmText: 'Continue', minLength: 3 },
    );
    if (reason === null) return;
    const ok = await confirm(`Permanently delete the application from ${row.full_name}? This cannot be undone.`,
      { title: 'Delete permanently', danger: true, requireText: 'DELETE', confirmText: 'Delete permanently' });
    if (!ok) return;
    setBusyId(row._id);
    try {
      await api.post(`/superadmin/deleted-applications/${row._id}/purge`, { reason: reason.trim(), confirm: 'DELETE' });
      toast('Application deleted permanently.', { kind: 'success' });
      await load();
      onChanged?.();
    } catch (e) { toast(errText(e, 'Failed to delete the application.'), { kind: 'error' }); }
    finally { setBusyId(''); }
  };

  return (
    <section className="perf-card card-pad" style={{ marginTop: 16 }} data-testid="deleted-applications">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>Deleted applications{rows?.length ? ` (${rows.length})` : ''}</h3>
      <p className="perf-lead">
        Soft-deleted applications are hidden from every other screen. Restore brings one back as pending; deleting it
        here removes it permanently.
      </p>
      {loadError && <p className="perf-msg" data-kind="error">{loadError}</p>}
      {rows === null && <p className="perf-note">Loading…</p>}
      {rows?.length === 0 && !loadError && <p className="perf-note">No deleted applications.</p>}
      {rows?.length > 0 && (
        <ScrollList maxHeight="45vh">
          {rows.map((r) => (
            <div key={r._id} className="perf-row">
              <span className="perf-row-title">{r.full_name}</span>
              <span className="perf-row-text">
                {r.student_id} · {r.position_title} · was {r.status || 'pending'} · deleted {when(r.deleted_at)} by {r.deleted_by || 'unknown'}.
                Reason: {r.delete_reason || 'none given'}
              </span>
              <button type="button" className="perf-btn" disabled={busyId === r._id} onClick={() => restore(r)}>Restore</button>
              <button type="button" className="perf-btn perf-btn-danger" disabled={busyId === r._id} onClick={() => purge(r)}>Delete permanently</button>
            </div>
          ))}
        </ScrollList>
      )}
    </section>
  );
}
