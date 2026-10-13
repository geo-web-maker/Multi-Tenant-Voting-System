import React, { useEffect, useMemo, useState } from 'react';
import api from '../api';
import { regNo } from '../regNo';
import { LoadingBlock } from './Spinner.jsx';
import { ScrollList } from './UIFeedback';
import { startPolling } from '../hooks/usePolling';
import { getTemplate } from '../template';

// Applicant list with stages, for the people who answer applicants' questions (IT admins) and for the
// Election Commission. Stage only: the server sends no votes or payment details to either role. The Commission's
// list also carries the final decision (date + stated reason) on decided applications, in `r.decision`.
const STAGE_TONE = {
  finance_pending: 'var(--warning)', finance_rejected: 'var(--danger)', with_panel: 'var(--info)',
  needs_decision: 'var(--warning)',
  approved: 'var(--success)', denied: 'var(--danger)', removed: 'var(--danger)',
};
// Blueprint pill tone per stage (the same ok / warn / neg / mute words its status pills already use).
const STAGE_PILL_TONE = { approved: 'ok', denied: 'neg', removed: 'mute', finance_rejected: 'neg' };
const STAGE_ORDER = ['finance_pending', 'finance_rejected', 'with_panel', 'needs_decision', 'approved', 'denied', 'removed'];

export default function ApplicationStages({ endpoint = '/it-admin/applications' }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [stage, setStage] = useState('all');
  const bp = getTemplate();   // render-time: null => the standard UI

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const res = await api.get(endpoint);
        if (live) { setRows(res.data); setError(''); }
      } catch { if (live) setError('Could not load applications. Try again shortly.'); }
    };
    load();
    const stop = startPolling(load, 30000);
    return () => { live = false; stop(); };
  }, [endpoint]);

  const counts = useMemo(() => {
    const c = {};
    (rows || []).forEach(r => { c[r.stage] = (c[r.stage] || 0) + 1; });
    return c;
  }, [rows]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows || []).filter(r => (stage === 'all' || r.stage === stage)
      && (!needle || r.full_name?.toLowerCase().includes(needle) || r.student_id?.toLowerCase().includes(needle)));
  }, [rows, q, stage]);

  const chip = (id, label, n) => (
    <button key={id} type="button" onClick={() => setStage(id)} aria-pressed={stage === id}
      style={{ padding: '6px 12px', borderRadius: 999, fontSize: 12, cursor: 'pointer', color: 'var(--text-color)',
        border: '1px solid var(--border-color)', fontWeight: stage === id ? 700 : 500,
        backgroundColor: stage === id ? 'color-mix(in srgb, var(--info) 18%, transparent)' : 'transparent' }}>
      {label} ({n})
    </button>
  );

  if (error && !rows) return <p style={{ opacity: 0.7 }}>{error}</p>;
  if (!rows) return <LoadingBlock text="Loading applications…" />;

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search by name or ID…"
        style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, width: '100%', boxSizing: 'border-box' }} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {chip('all', 'All', rows.length)}
        {STAGE_ORDER.filter(s => counts[s]).map(s => chip(s, rows.find(r => r.stage === s).stage_label, counts[s]))}
      </div>
      {shown.length === 0 && <p style={{ opacity: 0.55 }}>{rows.length === 0 ? 'No applications yet.' : 'No applications match.'}</p>}
      <ScrollList maxHeight="60vh">
        {shown.map(r => (
          <div key={r._id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap',
            padding: '12px 14px', border: '1px solid var(--border-color)', borderRadius: 10, marginBottom: 8, backgroundColor: 'var(--card-bg)' }}>
            <div>
              <b style={{ color: 'var(--text-color)' }}>{r.full_name}</b><br />
              <small style={{ opacity: 0.65 }}>{regNo(r.student_id)}{r.position_title ? ` · ${r.position_title}` : ''}</small>
            </div>
            {bp?.StatusPill
              ? <bp.StatusPill tone={STAGE_PILL_TONE[r.stage] || 'warn'}>{r.stage_label}</bp.StatusPill>
              : (
                <span style={{ padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, color: 'var(--text-color)',
                  border: `1px solid color-mix(in srgb, ${STAGE_TONE[r.stage]} 45%, transparent)`,
                  backgroundColor: `color-mix(in srgb, ${STAGE_TONE[r.stage]} 12%, transparent)` }}>
                  {r.stage_label}
                </span>
              )}
            {r.decision && (
              // Only the Election Commission's list carries this: the decision date and the final stated reason.
              <div style={{ flexBasis: '100%', fontSize: 12, color: 'var(--text-color)' }}>
                <div style={{ opacity: 0.6 }}>Decided: {r.decision.decided_at ? new Date(r.decision.decided_at).toLocaleDateString() : 'date not recorded'}</div>
                <div style={{ marginTop: 4, fontSize: 13 }}>Reason: {r.decision.final_reason || 'No reason recorded'}</div>
                {r.decision.superadmin_override && (
                  <div style={{ marginTop: 8, opacity: 0.55, fontStyle: 'italic' }}>This was decided by the superadmin. Panel voting was bypassed.</div>
                )}
              </div>
            )}
          </div>
        ))}
      </ScrollList>
    </div>
  );
}
