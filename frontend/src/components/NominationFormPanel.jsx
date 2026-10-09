import React from 'react';
import api from '../api';
import { getTemplate } from '../template';

const defaults = { enabled: false, required: true, title: 'Nomination Form', instructions: '', template_file: null, accepted_types: ['pdf'], max_mb: 5, collect_phone: false };

export default function NominationFormPanel() {
  const bp = getTemplate();
  const k = bp?.cls;
  const [saved, setSaved] = React.useState(defaults);
  const [form, setForm] = React.useState(defaults);
  const [reason, setReason] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [msg, setMsg] = React.useState({ kind: '', text: '' });
  const [testing, setTesting] = React.useState(false);
  const [test, setTest] = React.useState(null);   // { ok, steps: [{ name, ok, detail }] } or { error }

  const apply = (data) => { const next = { ...defaults, ...(data || {}) }; setSaved(next); setForm(next); };
  React.useEffect(() => { api.get('/nomination-form').then(r => apply(r.data)).catch(() => setMsg({ kind: 'error', text: 'Could not load the nomination-form settings.' })); }, []);

  const changed = JSON.stringify(form) !== JSON.stringify(saved);
  const sizeOk = Number.isInteger(form.max_mb) && form.max_mb >= 1 && form.max_mb <= 10;
  const typesOk = form.accepted_types.length > 0;
  const canSave = changed && sizeOk && typesOk && reason.trim().length >= 3 && !busy;
  const toggleType = (type) => setForm(f => ({ ...f, accepted_types: f.accepted_types.includes(type) ? f.accepted_types.filter(x => x !== type) : [...f.accepted_types, type] }));

  const uploadTemplate = async (file) => {
    if (!file) return;
    setUploading(true); setMsg({ kind: '', text: '' });
    try {
      const fd = new FormData(); fd.append('file', file); fd.append('reason', reason.trim() || 'Uploaded nomination form template');
      const r = await api.post('/superadmin/nomination-form/template', fd);
      apply(r.data); setReason(''); setMsg({ kind: 'ok', text: 'Template uploaded.' });
    } catch (e) { setMsg({ kind: 'error', text: e.response?.data?.detail || 'Template upload failed.' }); }
    finally { setUploading(false); }
  };

  const testStorage = async () => {
    setTesting(true); setTest(null);
    try { setTest((await api.post('/superadmin/nomination-form/test-storage')).data); }
    catch (e) { setTest({ error: e.response?.data?.detail || 'The test could not be run.' }); }
    finally { setTesting(false); }
  };

  const save = async () => {
    setBusy(true); setMsg({ kind: '', text: '' });
    try {
      const r = await api.put('/superadmin/nomination-form', { ...form, reason: reason.trim() });
      apply(r.data); setReason(''); setMsg({ kind: 'ok', text: 'Nomination-form settings saved.' });
    } catch (e) { setMsg({ kind: 'error', text: e.response?.data?.detail || 'Could not save the nomination-form settings.' }); }
    finally { setBusy(false); }
  };

  return (
    <div style={box} className={k?.card}>
      <h4 style={{ margin: '0 0 4px' }} className={k?.sec}>Nomination form</h4>
      <p style={{ margin: '0 0 14px', fontSize: 12, opacity: .65 }}>Configure the downloadable blank form and the completed form applicants must attach. Changes are audit-logged.</p>
      <div style={grid}>
        <label style={lbl}>Enable section <input type="checkbox" checked={Boolean(form.enabled)} onChange={e => setForm({ ...form, enabled: e.target.checked })} /></label>
        <label style={lbl}>Require upload <input type="checkbox" checked={Boolean(form.required)} disabled={!form.enabled} onChange={e => setForm({ ...form, required: e.target.checked })} /></label>
        <label style={lbl}>Ask applicants for a phone number <input type="checkbox" checked={Boolean(form.collect_phone)} onChange={e => setForm({ ...form, collect_phone: e.target.checked })} /></label>
      </div>
      {form.collect_phone && <p style={{ margin: '0 0 10px', fontSize: 12, opacity: .65 }}>For registers with no phone numbers. Saved on the voter record, and only when that record has none yet. Works even if the nomination form section above is off.</p>}
      <input style={inp} value={form.title} maxLength={80} placeholder="Nomination Form" onChange={e => setForm({ ...form, title: e.target.value })} aria-label="Nomination form title" />
      <textarea style={{ ...inp, minHeight: 100, marginTop: 8 }} value={form.instructions} maxLength={2000} placeholder="Instructions shown to applicants" onChange={e => setForm({ ...form, instructions: e.target.value })} aria-label="Nomination form instructions" />
      <div style={{ marginTop: 10 }}>
        <b style={{ fontSize: 12 }}>Accepted types</b>
        <label style={check}><input type="checkbox" checked={form.accepted_types.includes('pdf')} onChange={() => toggleType('pdf')} /> PDF</label>
        <label style={check}><input type="checkbox" checked={form.accepted_types.includes('docx')} onChange={() => toggleType('docx')} /> DOCX</label>
      </div>
      <label style={{ ...lbl, marginTop: 10 }}>Maximum size (MB) <input type="number" min="1" max="10" value={form.max_mb} onChange={e => setForm({ ...form, max_mb: Number(e.target.value) })} style={{ ...inp, width: 110, marginLeft: 8 }} /></label>
      <div style={uploadBox}>
        <b style={{ fontSize: 12 }}>Blank template</b>
        {form.template_file ? <span style={{ fontSize: 12, opacity: .75 }}>{form.template_file.filename}</span> : <span style={{ fontSize: 12, opacity: .55 }}>No template uploaded</span>}
        <label style={uploadBtn}>{uploading ? 'Uploading…' : 'Upload PDF/DOCX'}<input type="file" accept=".pdf,.docx" disabled={uploading} style={{ display: 'none' }} onChange={e => uploadTemplate(e.target.files?.[0])} /></label>
      </div>
      <div style={uploadBox}>
        <b style={{ fontSize: 12 }}>Signed-form storage</b>
        <span style={{ fontSize: 12, opacity: .6 }}>Checks the private bucket settings without submitting an application.</span>
        <button type="button" onClick={testStorage} disabled={testing} style={{ ...uploadBtn, background: 'transparent', color: 'inherit' }} data-testid="test-storage">{testing ? 'Testing…' : 'Test storage'}</button>
        {test && (
          <div role="status" style={{ flexBasis: '100%', fontSize: 12, lineHeight: 1.7 }}>
            {test.error ? <span style={{ color: 'var(--danger)' }}>{test.error}</span> : (
              <>
                <b style={{ color: test.ok ? 'var(--success)' : 'var(--danger)' }}>{test.ok ? 'Storage works: signed forms can be uploaded, read by staff and deleted.' : 'Storage is not working yet.'}</b>
                {test.steps.map(st => (
                  <div key={st.name}><span aria-hidden="true">{st.ok ? '✓' : '✗'}</span> <b>{st.name}</b>: <span style={{ opacity: .8 }}>{st.detail}</span></div>
                ))}
              </>
            )}
          </div>
        )}
      </div>
      <input style={{ ...inp, width: '100%', marginTop: 8, boxSizing: 'border-box' }} value={reason} maxLength={300} placeholder="Reason for change (required)" aria-label="Reason for change" onChange={e => setReason(e.target.value)} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
        <button onClick={save} disabled={!canSave} style={{ ...saveBtn, opacity: canSave ? 1 : .5 }} className={k?.btn}>{busy ? 'Saving…' : 'Save nomination-form settings'}</button>
        {(!typesOk || !sizeOk) && <span role="alert" style={{ fontSize: 12, color: 'var(--danger)' }}>{!typesOk ? 'Choose at least one file type.' : 'Maximum size must be 1–10 MB.'}</span>}
        {msg.text && <span role="status" style={{ fontSize: 12, color: msg.kind === 'error' ? 'var(--danger)' : 'var(--success)' }}>{msg.text}</span>}
      </div>
    </div>
  );
}

const box = { padding: 16, border: '1px solid var(--border-color)', borderRadius: 12, background: 'var(--card-bg)', marginBottom: 16 };
const inp = { padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', fontSize: 14, boxSizing: 'border-box', width: '100%' };
const lbl = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: 12, opacity: .8 };
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 10 };
const check = { display: 'inline-flex', gap: 6, margin: '6px 16px 0 0', fontSize: 12 };
const uploadBox = { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 12, padding: 10, borderRadius: 8, border: '1px solid var(--border-color)' };
const uploadBtn = { padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-color)', cursor: 'pointer', fontWeight: 600, marginLeft: 'auto' };
const saveBtn = { padding: '10px 16px', background: 'var(--success)', color: 'white', border: 0, borderRadius: 8, fontWeight: 700, cursor: 'pointer' };
