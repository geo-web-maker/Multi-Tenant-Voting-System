import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm } from './UIFeedback';
import { errMsg } from '../studentEdit';
import { useRevealReady } from './RevealGroup';

/**
 * Superadmin: which optional voter fields this organisation collects (gender, programme, or any custom
 * column). "Collect" = read from imports + admin turnout breakdown. "Publish" = also show turnout by
 * that field on the public results page after voting closes (never how anyone voted).
 */
export default function VoterFieldsPanel() {
  const toast = useToast();
  const confirm = useConfirm();
  const [d, setD] = useState(null);
  const [minGroup, setMinGroup] = useState(10);
  const [reason, setReason] = useState('');
  const [nf, setNf] = useState({ key: '', label: '' });
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = (await api.get('/superadmin/voter-fields')).data;
      setD(r); setMinGroup(r.min_group_size);
    } catch (e) { setFailed(true); toast(errMsg(e, 'Could not load voter fields.'), { kind: 'error' }); }
  }, [toast]);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);
  useRevealReady(Boolean(d) || failed);
  if (!d) return null;

  const save = async (body, okMsg) => {
    if (reason.trim().length < 3) { toast('Enter a reason for this change first.', { kind: 'error' }); return; }
    setBusy(true);
    try {
      const r = (await api.put('/superadmin/voter-fields', { reason: reason.trim(), ...body })).data;
      setD(r); setMinGroup(r.min_group_size); toast(okMsg, { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Could not save.'), { kind: 'error' }); }
    finally { setBusy(false); }
  };
  const toggle = (f, patch) => save({ fields: [{ key: f.key, ...patch }] }, 'Saved.');
  const purge = async f => {
    if (!(await confirm(`Erase every stored "${f.label}" value for this organisation? This cannot be undone.`, { confirmText: 'Erase' }))) return;
    save({ purge: [f.key] }, `Erased stored ${f.label} values.`);
  };
  const remove = async f => {
    if (!(await confirm(`Remove "${f.label}" and erase its stored values? This cannot be undone.`, { confirmText: 'Remove' }))) return;
    save({ remove: [f.key] }, `Removed ${f.label}.`);
  };
  const add = async () => {
    const key = nf.key.trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (!key) return;
    await save({ fields: [{ key, label: nf.label.trim() || undefined, enabled: true }] }, 'Field added.');
    setNf({ key: '', label: '' });
  };

  return (
    <div style={{ ...box, marginTop: 16 }}>
      <b style={{ fontSize: 14 }}>Optional voter fields</b>
      <p style={note}>
        Extra columns your import file may contain. A field only does anything once switched on. Values are free text and shown
        to admins only. "Publish" adds a turnout split to the public results after voting closes; it never shows how anyone voted.
        Switching a field off keeps its data; erase it explicitly if you no longer need it.
      </p>
      <label style={fld}>
        <span style={lbl}>Reason for the change (logged)</span>
        <input style={inp} value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. Women's Rep post needs a turnout split" />
      </label>

      <div style={{ marginTop: 12 }}>
        {d.fields.map(f => (
          <div key={f.key} style={row}>
            <div style={{ flex: 1, minWidth: 140 }}>
              <b style={{ fontSize: 13 }}>{f.label}</b>{' '}
              <span style={{ fontSize: 11, opacity: 0.55 }}>column: {f.key}{f.standard ? ' · standard' : ' · custom'}</span>
            </div>
            <label style={chk}><input type="checkbox" checked={f.enabled} disabled={busy} onChange={e => toggle(f, { enabled: e.target.checked })} /> Collect</label>
            <label style={chk}><input type="checkbox" checked={f.public} disabled={busy || !f.enabled} onChange={e => toggle(f, { public: e.target.checked })} /> Publish turnout</label>
            <button style={ghost} disabled={busy} onClick={() => purge(f)}>Erase data</button>
            {!f.standard && <button style={{ ...ghost, color: 'var(--danger)' }} disabled={busy} onClick={() => remove(f)}>Remove</button>}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12, alignItems: 'flex-end' }}>
        <label style={{ ...fld, flex: 1, minWidth: 120 }}><span style={lbl}>New field column</span>
          <input style={inp} value={nf.key} onChange={e => setNf({ ...nf, key: e.target.value })} placeholder="hostel" /></label>
        <label style={{ ...fld, flex: 1, minWidth: 120 }}><span style={lbl}>Display label</span>
          <input style={inp} value={nf.label} onChange={e => setNf({ ...nf, label: e.target.value })} placeholder="Hostel" /></label>
        <button style={btn} disabled={busy || !nf.key.trim()} onClick={add}>Add field</button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginTop: 12, flexWrap: 'wrap' }}>
        <label style={{ ...fld, width: 200 }}><span style={lbl}>Smallest group shown publicly</span>
          <input style={inp} type="number" min={5} max={100} value={minGroup} onChange={e => setMinGroup(Number(e.target.value))} /></label>
        <button style={btn} disabled={busy || minGroup === d.min_group_size} onClick={() => save({ min_group_size: minGroup }, 'Saved.')}>Save</button>
        <span style={{ fontSize: 12, opacity: 0.65 }}>Smaller groups are combined into "Other" on the public page.</span>
      </div>
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--bg-color)' };
const note = { fontSize: 12, opacity: 0.75, margin: '6px 0' };
const fld = { display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 };
const lbl = { fontSize: 12, opacity: 0.65, fontWeight: 600 };
const inp = { padding: '9px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, width: '100%', boxSizing: 'border-box' };
const btn = { padding: '10px 18px', color: 'var(--bp-ai, #fff)', background: 'var(--bp-ok, #2ecc71)', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 'bold', fontSize: 13 };
const ghost = { padding: '6px 10px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: 8, cursor: 'pointer', fontSize: 12 };
const row = { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', padding: '8px 0', borderBottom: '1px solid var(--border-color)' };
const chk = { display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 };
