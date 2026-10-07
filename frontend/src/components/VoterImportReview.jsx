import React, { useEffect, useMemo, useRef, useState } from 'react';
import api, { getErrorMessage } from '../api';
import { regNo } from '../regNo';
import ColumnMapper from './ColumnMapper';
import { mappingPayload, missingRequired, toMappingState } from '../columnMapping';

/**
 * Three-step roster update. The chosen file (CSV, TSV or Excel) is first read and its columns are
 * matched to the voter fields (POST /admin/import-voters/inspect, then the admin confirms or corrects
 * the guess). It is then only *compared* against the live voter list (POST /admin/import-voters/preview);
 * nothing is written until the admin picks an action for each group and confirms
 * (POST /admin/import-voters/apply). Existing voters keep their vote status,
 * roles and login credentials no matter what is chosen here.
 */
export default function VoterImportReview({ file, onClose, onDone }) {
  const [stage, setStage] = useState('map');        // 'map' = match columns, 'review' = compare with roster
  const [inspect, setInspect] = useState(null);
  const [mapping, setMapping] = useState({});
  const [mapBusy, setMapBusy] = useState(false);
  const inspectSeq = useRef(0);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('changed');
  const [applying, setApplying] = useState(false);

  const [newAction, setNewAction] = useState('add');
  const [changedDefault, setChangedDefault] = useState('apply');
  const [changedOverrides, setChangedOverrides] = useState({});
  const [phoneMode, setPhoneMode] = useState('replace');
  const [missingDefault, setMissingDefault] = useState('keep');
  const [missingOverrides, setMissingOverrides] = useState({});
  const [confirmText, setConfirmText] = useState('');

  // Reads the file and asks the server which row looks like the headings and which column is which.
  // Called again when the admin picks another sheet or heading row (the newest answer wins).
  const loadInspect = (opts = {}) => {
    const seq = ++inspectSeq.current;
    const fd = new FormData();
    fd.append('file', file);
    if (opts.sheet) fd.append('sheet', opts.sheet);
    if (opts.header_row) fd.append('header_row', String(opts.header_row));
    setMapBusy(true);
    api.post('/admin/import-voters/inspect', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(res => {
        if (seq !== inspectSeq.current) return;
        setInspect(res.data);
        setMapping(toMappingState(res.data.suggested_mapping));
        setError('');
      })
      .catch(e => { if (seq === inspectSeq.current) setError(getErrorMessage(e, 'Could not read that file.')); })
      .finally(() => { if (seq === inspectSeq.current) setMapBusy(false); });
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadInspect(); }, [file]);

  const runPreview = () => {
    setStage('review');
    setPreview(null);
    setError('');
    setChangedOverrides({});
    setMissingOverrides({});
    const fd = new FormData();
    fd.append('file', file);
    fd.append('mapping', JSON.stringify(mappingPayload(mapping)));
    fd.append('header_row', String(inspect.header_row));
    if (inspect.sheet) fd.append('sheet', inspect.sheet);
    api.post('/admin/import-voters/preview', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(res => {
        setPreview(res.data);
        const s = res.data.summary;
        setTab(s.changed ? 'changed' : s.new ? 'new' : s.missing ? 'missing' : 'warnings');
      })
      .catch(e => setError(getErrorMessage(e, 'Could not read that file.')));
  };

  const backToMap = () => { setStage('map'); setPreview(null); setError(''); };
  const missing = inspect ? missingRequired(inspect, mapping) : [];

  const changedValue = sid => changedOverrides[sid] ?? changedDefault;
  const missingValue = sid => missingOverrides[sid] ?? missingDefault;

  const removalCount = useMemo(() => (preview?.missing || []).filter(m => !m.protected && missingValue(m.student_id) === 'remove').length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [preview, missingOverrides, missingDefault]);
  const needsConfirm = removalCount > 0;
  const canApply = preview && !applying && (!needsConfirm || confirmText.trim().toUpperCase() === 'REMOVE');

  const apply = async () => {
    setApplying(true);
    try {
      const res = await api.post('/admin/import-voters/apply', {
        preview_id: preview.preview_id, new_action: newAction,
        changed_default: changedDefault, changed_overrides: changedOverrides, phone_mode: phoneMode,
        missing_default: missingDefault, missing_overrides: missingOverrides,
      });
      onDone(res.data);
    } catch (e) {
      setError(getErrorMessage(e, 'Import failed.'));
      setApplying(false);
    }
  };

  const s = preview?.summary;
  const fieldLabel = k => s?.fields_in_file.find(f => f.key === k)?.label || k;
  const tabs = preview ? [
    { id: 'changed', label: `Changed (${s.changed})` },
    { id: 'new', label: `New (${s.new})` },
    { id: 'missing', label: `Not in file (${s.missing})` },
    { id: 'warnings', label: `Warnings (${s.warning_count + s.skipped_rows})` },
  ] : [];

  return (
    <div style={overlay}>
      <div style={modal}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, color: 'var(--text-color)' }}>{stage === 'map' ? 'Match file columns' : 'Review voter update'}</h3>
          <button style={ghostBtn} onClick={onClose} disabled={applying}>Cancel</button>
        </div>
        {stage === 'review' && (
          <button style={{ ...ghostBtn, marginBottom: 10 }} onClick={backToMap} disabled={applying}>← Change column matching</button>
        )}
        <p style={{ margin: '0 0 12px', fontSize: 12, opacity: 0.6 }}>
          {file.name} — nothing changes until you press Apply. Vote status, roles and admin logins of existing voters are never touched.
        </p>
        {stage === 'review' && preview && s.fields_in_file.length > 0 && (
          <p style={{ margin: '0 0 12px', fontSize: 12, opacity: 0.75 }}>
            Also reading: {s.fields_in_file.map(f => f.label).join(', ')}.
            {s.attr_fills > 0 && ` ${s.attr_fills} voter(s) with an empty value will be filled from the file automatically; existing values are only replaced if you apply a change below.`}
          </p>
        )}

        {error && <p style={{ color: 'var(--bp-no, #e74c3c)', fontSize: 13 }}>{error}</p>}
        {stage === 'map' && (
          <>
            {!inspect && !error && <p style={{ opacity: 0.6 }}>Reading the file…</p>}
            {inspect && (
              <ColumnMapper data={inspect} mapping={mapping} onMapping={setMapping} busy={mapBusy}
                onSheet={sheet => loadInspect({ sheet })}
                onHeaderRow={header_row => loadInspect({ sheet: inspect.sheet, header_row })} />
            )}
            {inspect && (
              <button style={{ ...primaryBtn, marginTop: 14, opacity: missing.length || mapBusy ? 0.5 : 1 }}
                disabled={missing.length > 0 || mapBusy} onClick={runPreview}>
                {missing.length ? `Choose a column for ${missing.map(m => m.label).join(' and ')}` : 'Continue — compare with current voters'}
              </button>
            )}
          </>
        )}
        {stage === 'review' && !preview && !error && <p style={{ opacity: 0.6 }}>Comparing with the current voter list…</p>}

        {stage === 'review' && preview && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8, marginBottom: 12 }}>
              {[['In file', s.file_rows], ['Unchanged', s.unchanged], ['Changed', s.changed], ['New', s.new], ['Not in file', s.missing]].map(([l, v]) => (
                <div key={l} style={stat}><span style={{ fontSize: 11, opacity: 0.55 }}>{l}</span><b style={{ fontSize: 18 }}>{v}</b></div>
              ))}
            </div>

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              {tabs.map(t => (
                <button key={t.id} onClick={() => setTab(t.id)} style={{ ...pill, ...(tab === t.id ? pillActive : {}) }}>{t.label}</button>
              ))}
            </div>

            <div style={{ maxHeight: '42vh', overflowY: 'auto', marginBottom: 12 }}>
              {tab === 'changed' && (
                <>
                  <div style={optRow}>
                    <label>For all changed voters:&nbsp;
                      <select style={sel} value={changedDefault} onChange={e => { setChangedDefault(e.target.value); setChangedOverrides({}); }}>
                        <option value="apply">Apply the file's details</option>
                        <option value="skip">Keep current details</option>
                      </select>
                    </label>
                    <label>Phone numbers:&nbsp;
                      <select style={sel} value={phoneMode} onChange={e => setPhoneMode(e.target.value)}>
                        <option value="replace">Replace with file's numbers</option>
                        <option value="merge">Keep old + add new numbers</option>
                      </select>
                    </label>
                  </div>
                  {preview.changed.length === 0 && <p style={{ opacity: 0.5 }}>No existing voter differs from the file.</p>}
                  {preview.changed.map(c => (
                    <div key={c.student_id} style={row}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <b style={{ fontSize: 13 }}>{regNo(c.student_id)}</b>
                        {c.staff && <div style={{ fontSize: 11, color: 'var(--warning)' }}>Admin / commissioner account — only a superadmin can apply this change</div>}
                        {c.name_changed && <div style={diffLine}>Name: <s style={{ opacity: 0.5 }}>{c.old_name}</s> → <b>{c.new_name}</b></div>}
                        {c.phones_changed && <div style={diffLine}>Phones: <s style={{ opacity: 0.5 }}>{c.old_phones.join(', ') || 'none'}</s> → <b>{c.new_phones.join(', ') || 'none'}</b></div>}
                        {Object.entries(c.attrs_changed || {}).map(([k, v]) => (
                          <div key={k} style={diffLine}>{fieldLabel(k)}: <s style={{ opacity: 0.5 }}>{v.old}</s> → <b>{v.new}</b></div>
                        ))}
                      </div>
                      <select style={sel} value={changedValue(c.student_id)}
                        onChange={e => setChangedOverrides(o => ({ ...o, [c.student_id]: e.target.value }))}>
                        <option value="apply">Apply</option>
                        <option value="skip">Skip</option>
                      </select>
                    </div>
                  ))}
                </>
              )}

              {tab === 'new' && (
                <>
                  <div style={optRow}>
                    <label>New voters:&nbsp;
                      <select style={sel} value={newAction} onChange={e => setNewAction(e.target.value)}>
                        <option value="add">Add them to the roster</option>
                        <option value="skip">Don't add any</option>
                      </select>
                    </label>
                  </div>
                  {preview.new.length === 0 && <p style={{ opacity: 0.5 }}>Every registration number in the file already exists.</p>}
                  {preview.new.map(r => (
                    <div key={r.student_id} style={row}>
                      <div style={{ flex: 1 }}><b style={{ fontSize: 13 }}>{regNo(r.student_id)}</b> <span style={{ fontSize: 12, opacity: 0.7 }}>{r.full_name}</span></div>
                      <span style={{ fontSize: 11, opacity: 0.5 }}>{[...Object.values(r.attrs || {}), ...r.phones].join(', ')}</span>
                    </div>
                  ))}
                </>
              )}

              {tab === 'missing' && (
                <>
                  <div style={optRow}>
                    <label>Voters not in this file:&nbsp;
                      <select style={sel} value={missingDefault} onChange={e => { setMissingDefault(e.target.value); setMissingOverrides({}); }}>
                        <option value="keep">Keep them (recommended)</option>
                        <option value="remove">Remove them from the roster</option>
                      </select>
                    </label>
                  </div>
                  <p style={{ fontSize: 11, opacity: 0.55, margin: '0 0 8px' }}>
                    Anyone who has voted, holds an admin/commissioner role, or has an application is always kept.
                  </p>
                  {preview.missing.length === 0 && <p style={{ opacity: 0.5 }}>Everyone on the roster is in the file.</p>}
                  {preview.missing.map(m => (
                    <div key={m.student_id} style={row}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <b style={{ fontSize: 13 }}>{regNo(m.student_id)}</b> <span style={{ fontSize: 12, opacity: 0.7 }}>{m.full_name}</span>
                        {m.protected && <div style={{ fontSize: 11, color: 'var(--warning)' }}>Protected: {m.protected_reasons.join(', ')}</div>}
                      </div>
                      <select style={sel} disabled={m.protected} value={m.protected ? 'keep' : missingValue(m.student_id)}
                        onChange={e => setMissingOverrides(o => ({ ...o, [m.student_id]: e.target.value }))}>
                        <option value="keep">Keep</option>
                        <option value="remove">Remove</option>
                      </select>
                    </div>
                  ))}
                </>
              )}

              {tab === 'warnings' && (
                <>
                  {s.skipped_rows > 0 && <p style={{ fontSize: 13 }}>{s.skipped_rows} row(s) skipped (missing or invalid student_id / full_name).</p>}
                  {preview.warnings.length === 0 && s.skipped_rows === 0 && <p style={{ opacity: 0.5 }}>No warnings.</p>}
                  {preview.warnings.map((w, i) => <p key={i} style={{ fontSize: 12, margin: '4px 0' }}>{w}</p>)}
                  {s.warning_count > preview.warnings.length && <p style={{ fontSize: 11, opacity: 0.5 }}>…and {s.warning_count - preview.warnings.length} more.</p>}
                </>
              )}
            </div>

            {needsConfirm && (
              <div style={{ marginBottom: 12 }}>
                <p style={{ fontSize: 12, color: 'var(--bp-no, #e74c3c)', margin: '0 0 6px' }}>
                  {removalCount} voter(s) will be permanently removed. Type REMOVE to confirm.
                </p>
                <input style={{ ...sel, width: '100%' }} value={confirmText} onChange={e => setConfirmText(e.target.value)} placeholder="REMOVE" />
              </div>
            )}

            <button style={{ ...primaryBtn, opacity: canApply ? 1 : 0.5 }} disabled={!canApply} onClick={apply}>
              {applying ? 'Applying…' : 'Apply update'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const overlay = { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.75)', zIndex: 3000, display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 16 };
const modal = { width: '100%', maxWidth: 720, maxHeight: '92vh', overflowY: 'auto', background: 'var(--card-bg)', color: 'var(--text-color)', border: '1px solid var(--border-color)', borderRadius: 16, padding: 24 };
const stat = { display: 'flex', flexDirection: 'column', gap: 2, padding: '10px 12px', border: '1px solid var(--border-color)', borderRadius: 10, background: 'var(--bg-color)' };
const pill = { padding: '7px 12px', borderRadius: 999, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', cursor: 'pointer', fontSize: 12 };
const pillActive = { borderColor: 'var(--info)', color: 'var(--info)', fontWeight: 600 };
const optRow = { display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, marginBottom: 10 };
const row = { display: 'flex', gap: 10, alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border-color)' };
const diffLine = { fontSize: 12, marginTop: 2, overflowWrap: 'anywhere' };
const sel = { padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', fontSize: 12 };
const ghostBtn = { padding: '8px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: 8, cursor: 'pointer', fontSize: 13 };
const primaryBtn = { width: '100%', padding: 12, background: 'var(--bp-ok, #2ecc71)', color: 'var(--bp-ai, #fff)', border: 'none', borderRadius: 8, fontWeight: 700, cursor: 'pointer' };
