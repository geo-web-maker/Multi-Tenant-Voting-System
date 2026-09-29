import React, { useEffect, useState } from 'react';
import api from '../api';
import { useRevealReady } from './RevealGroup';

/**
 * Turnout by voter field (gender, programme, any custom field the org switched on).
 * Counts only: who turned out, never how anyone voted. The server decides what each audience may see:
 *  - AdminTurnoutBreakdown: live, all groups, every enabled field (/admin/analytics/turnout-breakdown)
 *  - PublicTurnoutBreakdown: only fields marked public, only after the election closes, small groups
 *    already folded into "Other" (/election-results/turnout-breakdown)
 */
function FieldTable({ label, groups, note }) {
  return (
    <div style={{ marginTop: 14 }}>
      <b style={{ fontSize: 13 }}>{label}</b>
      {groups.length === 0 ? (
        <p style={muted}>{note || 'No data.'}</p>
      ) : (
        <div style={{ marginTop: 6 }}>
          {groups.map(g => (
            <div key={g.label} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                <span style={{ overflowWrap: 'anywhere' }}>{g.label}</span>
                <span style={{ whiteSpace: 'nowrap' }}><b>{g.voted}</b> / {g.registered} ({g.pct}%)</span>
              </div>
              <div style={{ height: 6, background: 'var(--border-color)', borderRadius: 3, overflow: 'hidden', marginTop: 3 }}>
                <div style={{ width: `${Math.min(100, g.pct)}%`, height: '100%', background: 'var(--info)' }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AdminTurnoutBreakdown() {
  const [data, setData] = useState(null);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () => api.get('/admin/analytics/turnout-breakdown').then(r => live && setData(r.data)).catch(() => {}).finally(() => live && setSettled(true));
    load();
    const id = setInterval(load, 30000);
    return () => { live = false; clearInterval(id); };
  }, []);
  useRevealReady(settled);
  if (!data || data.fields.length === 0) return null;
  return (
    <div style={{ ...panel, marginTop: 14 }} className="card-pad">
      <strong style={{ fontSize: 13 }}>Turnout by group</strong>
      <p style={muted}>Voted / registered. Visible to admins only; small groups are shown here but never published.</p>
      {data.fields.map(f => (
        <FieldTable key={f.key} label={<>{f.label}{f.public && <span style={pill}>public after close</span>}</>} groups={f.groups} />
      ))}
    </div>
  );
}

export function PublicTurnoutBreakdown() {
  const [data, setData] = useState(null);
  useEffect(() => {
    let live = true, id = null;
    const load = () => api.get('/election-results/turnout-breakdown').then(r => {
      if (!live) return;
      setData(r.data);
      if (r.data.available && id) clearInterval(id);     // final once closed: stop polling
    }).catch(() => {});
    load();
    id = setInterval(load, 60000);
    return () => { live = false; clearInterval(id); };
  }, []);
  if (!data?.available || data.fields.length === 0) return null;
  return (
    <div style={{ marginTop: 40, padding: 25, backgroundColor: 'var(--card-bg)', borderRadius: 15, border: '1px solid var(--border-color)' }}>
      <h3 style={{ fontSize: 18, color: 'var(--text-color)', margin: '0 0 4px' }}>Turnout by group</h3>
      {data.fields.map(f => (
        <FieldTable key={f.key} label={f.label} groups={f.groups}
          note="Not shown: the groups are too small to publish without identifying individuals." />
      ))}
      <p style={{ fontSize: 11, color: '#64748b', marginTop: 14 }}>
        Turnout only, not how anyone voted. Groups under {data.min_group_size} registered voters are combined into "Other".
      </p>
    </div>
  );
}

const panel = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)' };
const muted = { fontSize: 12, opacity: 0.65, margin: '4px 0' };
const pill = { marginLeft: 8, fontSize: 10, padding: '2px 8px', borderRadius: 999, border: '1px solid var(--border-color)', opacity: 0.8, fontWeight: 400 };
