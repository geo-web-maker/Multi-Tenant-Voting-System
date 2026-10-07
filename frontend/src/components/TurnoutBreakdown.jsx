import React, { useEffect, useState } from 'react';
import api from '../api';
import { startPolling } from '../hooks/usePolling';
import { useRevealReady } from './RevealGroup';
import { getTemplate } from '../template';

/**
 * Turnout by voter field (gender, programme, any custom field the org switched on).
 * Counts only: who turned out, never how anyone voted. The server decides what each audience may see:
 *  - AdminTurnoutBreakdown: live, all groups, every enabled field (/admin/analytics/turnout-breakdown)
 *  - PublicTurnoutBreakdown: only fields marked public, only after the election closes, small groups
 *    already folded into "Other" (/election-results/turnout-breakdown)
 */
function FieldTable({ label, groups, note }) {
  const bp = getTemplate();
  return (
    <div style={{ marginTop: 14 }}>
      <b style={{ fontSize: 13 }}>{label}</b>
      {groups.length === 0 ? (
        <p style={muted}>{note || 'No data.'}</p>
      ) : (
        <div style={{ marginTop: 6 }}>
          {groups.map(g => {
            // Blueprint: the group becomes a meter (turnout bar in the accent); default keeps the original div + inline bar.
            const Row = bp ? bp.Meter : 'div';
            const rowProps = bp ? { pct: Math.min(100, g.pct), accent: true } : { style: { marginBottom: 8 } };
            return (
            <Row key={g.label} {...rowProps}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                <span style={{ overflowWrap: 'anywhere' }}>{g.label}</span>
                <span style={{ whiteSpace: 'nowrap' }}><b>{g.voted}</b> / {g.registered} ({g.pct}%)</span>
              </div>
              {!bp && (
                <div style={{ height: 6, background: 'var(--border-color)', borderRadius: 3, overflow: 'hidden', marginTop: 3 }}>
                  <div style={{ width: `${Math.min(100, g.pct)}%`, height: '100%', background: 'var(--info)' }} />
                </div>
              )}
            </Row>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AdminTurnoutBreakdown() {
  const bp = getTemplate();
  const [data, setData] = useState(null);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () => api.get('/admin/analytics/turnout-breakdown').then(r => live && setData(r.data)).catch(() => {}).finally(() => live && setSettled(true));
    load();
    const stop = startPolling(load, 30000);
    return () => { live = false; stop(); };
  }, []);
  useRevealReady(settled);
  if (!data || data.fields.length === 0) return null;
  return (
    <div style={bp ? { marginTop: 14 } : { ...panel, marginTop: 14 }} className={bp ? bp.cls.card : 'card-pad'}>
      <strong style={{ fontSize: 13 }}>Turnout by group</strong>
      <p style={muted}>Voted / registered. Visible to admins only; small groups are shown here but never published.</p>
      {data.fields.map(f => (
        <FieldTable key={f.key} label={<>{f.label}{f.public && (bp ? <> <bp.Pill tone="mute">public after close</bp.Pill></> : <span style={pill}>public after close</span>)}</>} groups={f.groups} />
      ))}
    </div>
  );
}

export function PublicTurnoutBreakdown() {
  const bp = getTemplate();
  const [data, setData] = useState(null);
  useEffect(() => {
    let live = true, stop = null;
    const load = () => api.get('/election-results/turnout-breakdown').then(r => {
      if (!live) return;
      setData(r.data);
      if (r.data.available && stop) stop();     // final once closed: stop polling
    }).catch(() => {});
    load();
    stop = startPolling(load, 60000);
    return () => { live = false; stop(); };
  }, []);
  if (!data?.available || data.fields.length === 0) return null;
  return (
    <div style={bp ? { marginTop: 40 } : { marginTop: 40, padding: 25, backgroundColor: 'var(--card-bg)', borderRadius: 15, border: '1px solid var(--border-color)' }} className={bp ? bp.cls.card : undefined}>
      <h3 style={{ fontSize: 18, color: 'var(--text-color)', margin: '0 0 4px' }}>Turnout by group</h3>
      {data.fields.map(f => (
        <FieldTable key={f.key} label={f.label} groups={f.groups}
          note="Not shown: the groups are too small to publish without identifying individuals." />
      ))}
      <p style={{ fontSize: 11, color: 'var(--bp-mu, #64748b)', marginTop: 14 }}>
        Turnout only, not how anyone voted. Groups under {data.min_group_size} registered voters are combined into "Other".
      </p>
    </div>
  );
}

const panel = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)' };
const muted = { fontSize: 12, opacity: 0.65, margin: '4px 0' };
const pill = { marginLeft: 8, fontSize: 10, padding: '2px 8px', borderRadius: 999, border: '1px solid var(--border-color)', opacity: 0.8, fontWeight: 400 };
