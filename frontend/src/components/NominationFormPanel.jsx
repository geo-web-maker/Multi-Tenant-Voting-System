import React from 'react';
import api from '../api';

const defaults = { enabled: false, required: true, title: 'Nomination Form', instructions: '', template_file: null, accepted_types: ['pdf'], max_mb: 5, collect_phone: false };

export default function NominationFormPanel() {
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
    <section className="perf-card card-pad" style={{ marginBottom: 16 }} aria-label="Nomination form settings">
      <h3 style={h3}>Nomination form</h3>
      <p className="perf-lead">Configure the downloadable blank form and the completed form applicants must attach. Changes are audit-logged.</p>
      <div className="perf-checks">
        <label className="perf-check"><input type="checkbox" checked={Boolean(form.enabled)} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> Enable section</label>
        <label className="perf-check"><input type="checkbox" checked={Boolean(form.required)} disabled={!form.enabled} onChange={e => setForm({ ...form, required: e.target.checked })} /> Require upload</label>
        <label className="perf-check"><input type="checkbox" checked={Boolean(form.collect_phone)} onChange={e => setForm({ ...form, collect_phone: e.target.checked })} /> Ask applicants for a phone number</label>
      </div>
      {form.collect_phone && <p className="perf-note">For registers with no phone numbers. Saved on the voter record, and only when that record has none yet. Works even if the nomination form section above is off.</p>}
      <div className="perf-stack" style={{ marginTop: 12 }}>
        <input className="perf-field" value={form.title} maxLength={80} placeholder="Nomination Form" onChange={e => setForm({ ...form, title: e.target.value })} aria-label="Nomination form title" />
        <textarea className="perf-field" value={form.instructions} maxLength={2000} placeholder="Instructions shown to applicants" onChange={e => setForm({ ...form, instructions: e.target.value })} aria-label="Nomination form instructions" />
      </div>
      <div style={{ marginTop: 12 }}>
        <b style={{ fontSize: 13 }}>Accepted types</b>
        <div className="perf-btnbar" style={{ columnGap: 16 }}>
          <label className="perf-check"><input type="checkbox" checked={form.accepted_types.includes('pdf')} onChange={() => toggleType('pdf')} /> PDF</label>
          <label className="perf-check"><input type="checkbox" checked={form.accepted_types.includes('docx')} onChange={() => toggleType('docx')} /> DOCX</label>
        </div>
      </div>
      <label className="perf-check" style={{ marginTop: 4 }}>Maximum size (MB) <input className="perf-field" type="number" min="1" max="10" value={form.max_mb} onChange={e => setForm({ ...form, max_mb: Number(e.target.value) })} style={{ width: 110 }} /></label>
      <div className="perf-row">
        <span className="perf-row-title">Blank template</span>
        <span className="perf-row-text">{form.template_file ? form.template_file.filename : 'No template uploaded'}</span>
        <label className="perf-btn">{uploading ? 'Uploading…' : 'Upload PDF/DOCX'}<input type="file" accept=".pdf,.docx" disabled={uploading} style={{ display: 'none' }} onChange={e => uploadTemplate(e.target.files?.[0])} /></label>
      </div>
      <div className="perf-row">
        <span className="perf-row-title">Signed-form storage</span>
        <span className="perf-row-text">Checks the private bucket settings without submitting an application.</span>
        <button type="button" className="perf-btn" onClick={testStorage} disabled={testing} data-testid="test-storage">{testing ? 'Testing…' : 'Test storage'}</button>
        {test && (
          <div role="status" style={{ flexBasis: '100%', fontSize: 12, lineHeight: 1.7 }}>
            {test.error ? <span className="perf-msg" data-kind="error">{test.error}</span> : (
              <>
                <b className="perf-msg" data-kind={test.ok ? 'ok' : 'error'}>{test.ok ? 'Storage works: signed forms can be uploaded, read by staff and deleted.' : 'Storage is not working yet.'}</b>
                {test.steps.map(st => (
                  <div key={st.name}><span aria-hidden="true">{st.ok ? '✓' : '✗'}</span> <b>{st.name}</b>: <span className="perf-row-text">{st.detail}</span></div>
                ))}
              </>
            )}
          </div>
        )}
      </div>
      <input className="perf-field" style={{ width: '100%', marginTop: 12 }} value={reason} maxLength={300} placeholder="Reason for change (required)" aria-label="Reason for change" onChange={e => setReason(e.target.value)} />
      <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 12 }}>
        <button type="button" onClick={save} disabled={!canSave} className="perf-btn perf-btn-primary">{busy ? 'Saving…' : 'Save nomination-form settings'}</button>
        {(!typesOk || !sizeOk) && <span role="alert" className="perf-msg" data-kind="error">{!typesOk ? 'Choose at least one file type.' : 'Maximum size must be 1–10 MB.'}</span>}
        {msg.text && <span role="status" className="perf-msg" data-kind={msg.kind === 'error' ? 'error' : 'ok'}>{msg.text}</span>}
      </div>
    </section>
  );
}

const h3 = { margin: '0 0 6px', fontSize: 15 };
