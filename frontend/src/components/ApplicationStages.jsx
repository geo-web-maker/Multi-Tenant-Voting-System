import React, { useEffect, useMemo, useState } from 'react';
import api from '../api';
import { regNo } from '../regNo';
import { LoadingBlock } from './Spinner.jsx';
import { ScrollList } from './UIFeedback';
import { startPolling } from '../hooks/usePolling';

// Applicant list with stages, for the people who answer applicants' questions (IT admins).
// Stage only: the server sends no votes, reasons or payment details to this role.
const STAGE_TONE = {
  finance_pending: 'var(--warning)', finance_rejected: 'var(--danger)', with_panel: 'var(--info)',
  needs_decision: 'var(--warning)',
  approved: 'var(--success)', denied: 'var(--danger)', removed: 'var(--danger)',
};
const STAGE_ORDER = ['finance_pending', 'finance_rejected', 'with_panel', 'needs_decision', 'approved', 'denied', 'removed'];

export default function ApplicationStages() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [stage, setStage] = useState('all');

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const res = await api.get('/it-admin/applications');
        if (live) { setRows(res.data); setError(''); }
      } catch { if (live) setError('Could not load applications. Try again shortly.'); }
    };
    load();
    const stop = startPolling(load, 30000);
    return () => { live = false; stop(); };
  }, []);

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
            <span style={{ padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, color: 'var(--text-color)',
              border: `1px solid color-mix(in srgb, ${STAGE_TONE[r.stage]} 45%, transparent)`,
              backgroundColor: `color-mix(in srgb, ${STAGE_TONE[r.stage]} 12%, transparent)` }}>
              {r.stage_label}
            </span>
          </div>
        ))}
      </ScrollList>
    </div>
  );
}
