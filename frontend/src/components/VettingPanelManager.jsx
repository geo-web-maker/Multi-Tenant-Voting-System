import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm, ScrollList } from './UIFeedback';
import ViewAsButton from './ViewAsButton';
import { regNo } from '../regNo';

// Superadmin: appoint, reissue credentials for and (de)activate Vetting Panel members (guide 6.3, 7, 13.1).
const BLANK = {
  full_name: '', email: '', phone: '', is_member: false, student_id: '',
  affiliation: '', appointment_reason: '', access_ends: '', expires_with_phase: '',
};

const RISK_NOTICE = {
  chair_resolves: { tone: 'info', text: 'Ties are possible; the Chairperson breaks them.' },
  superadmin_only: {
    tone: 'warning',
    text: 'Ties are possible and only the superadmin can resolve them. Add one panelist or add the Chairperson.',
  },
};

const PHASE_OPTIONS = [['applications', 'Applications'], ['vetting', 'Vetting'], ['campaign', 'Campaign'],
  ['voting', 'Voting'], ['results', 'Results']];
const phaseEnd = (src, k) => src?.phase_schedule?.[k]?.end || null;
const phaseLabel = (src, k, label) => {
  const end = phaseEnd(src, k);
  return end ? `${label} closes (${new Date(end).toLocaleString()})` : `${label} closes (no end date set)`;
};

export default function VettingPanelManager({ voters = [], commissioners = [] }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState({ panel: [], panel_count: 0, tie_risk: 'none' });
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null);   // panel_member_id whose details are being edited
  const [mode, setMode] = useState('commissioners');       // 'commissioners' = quick-pick current commissioners, 'roll' = any voter, 'external' = outside person
  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState(null);     // the voter chosen from the roll, awaiting credentials

  const load = useCallback(async () => {
    try {
      const res = await api.get('/superadmin/vetting-panel');
      setData(res.data);
    } catch (e) {
      toast(e.response?.data?.detail || 'Could not load the Vetting Panel.', { kind: 'error' });
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  const linkCommissioner = async (e) => {
    e.preventDefault();
    if (!form.appointment_reason.trim()) return toast('An appointment reason is required.', { kind: 'error' });
    setSaving(true);
    try {
      // No email, phone or password: they reach the panel from their own Commission screen.
      await api.post('/superadmin/vetting-panel/link-commissioner', {
        student_id: picked.student_id, appointment_reason: form.appointment_reason,
      });
      toast(`${picked.full_name} can now open the Vetting Panel from their commissioner screen.`);
      setForm(BLANK);
      setPicked(null);
      await load();
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not add the commissioner.', { kind: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const addPanelist = async (e) => {
    e.preventDefault();
    if (!form.appointment_reason.trim()) return toast('An appointment reason is required.', { kind: 'error' });
    if (!form.is_member && !form.access_ends && !form.expires_with_phase) {
      return toast('An external panelist needs an access end: a date or a timeline phase.', { kind: 'error' });
    }
    setSaving(true);
    try {
      const body = {
        full_name: form.full_name, email: form.email, phone: form.phone,
        is_member: form.is_member, appointment_reason: form.appointment_reason,
        affiliation: form.affiliation,
        student_id: form.is_member ? form.student_id : null,
        access_expires_at: form.access_ends ? new Date(form.access_ends).toISOString() : null,
        expires_with_phase: form.expires_with_phase || null,
      };
      await api.post('/superadmin/vetting-panel', body);
      toast('Panelist added. Temporary password sent by SMS.');
      setForm(BLANK);
      setPicked(null);
      await load();
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not add the panelist.', { kind: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const reissue = async (p) => {
    try {
      await api.post(`/superadmin/vetting-panel/${p.panel_member_id}/set-credentials`, { email: p.email });
      toast('New temporary password sent.');
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not reissue credentials.', { kind: 'error' });
    }
  };

  const setActive = async (p, active) => {
    if (!active) {
      const ok = await confirm(`Deactivate ${p.full_name}? Their access ends now; recorded votes stay.`, {
        danger: true, confirmText: 'Deactivate',
      });
      if (!ok) return;
    }
    try {
      await api.post(`/superadmin/vetting-panel/${p.panel_member_id}/active`, null, { params: { active } });
      await load();
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not change this panelist.', { kind: 'error' });
    }
  };

  const notice = RISK_NOTICE[data.tie_risk];
  const minPanel = data.min_panel || 3;
  const chair = data.panel.find((p) => p.is_chair);
  const chairLine = chair
    ? (chair.active ? `The Chairperson, ${chair.full_name}, is on the panel.` : `The Chairperson, ${chair.full_name}, is on the panel list but inactive.`)
    : 'The Chairperson is not on the panel.';

  const onPanel = new Set(data.panel.map((p) => (p.student_id || '').toLowerCase()).filter(Boolean));
  const q = search.trim().toLowerCase();
  const matches = voters
    .filter((v) => !onPanel.has((v.student_id || '').toLowerCase()))
    .filter((v) => !q || v.full_name?.toLowerCase().includes(q) || v.student_id?.toLowerCase().includes(q));
  const SHOWN = 50;

  const commOptions = commissioners
    .filter((c) => !onPanel.has((c.student_id || '').toLowerCase()))
    .filter((c) => !q || c.full_name?.toLowerCase().includes(q) || c.student_id?.toLowerCase().includes(q));
  const pickVoter = (v) => {
    setPicked(v);
    setForm({ ...BLANK, is_member: true, student_id: v.student_id, full_name: v.full_name || '' });
  };
  const switchMode = (m) => { setMode(m); setPicked(null); setForm(BLANK); setSearch(''); };
  const showForm = mode === 'external' || picked;

  return (
    <div>
      <h3 style={heading}>Vetting Panel ({data.panel_count} active)</h3>

      {notice && (
        <div style={notice.tone === 'warning' ? warnBox : infoBox}>{notice.text}</div>
      )}
      <p style={{ ...meta, marginBottom: 14 }}>
        {chairLine} The panel needs at least {minPanel} active panelists.
        {data.frozen
          ? ' Vetting is open, so the panel is frozen: only extending a panelist’s access date is allowed.'
          : ' The panel freezes while vetting is open.'}
      </p>

      <div style={twoCol}>
        {/* ── Left: who is on the panel now (same card + row layout as the Overseers tab) ── */}
        <div style={card}>
          <h4 style={cardTitle}>Current Panel ({data.panel.length})</h4>
          {data.panel.length === 0 && (
            <p style={{ opacity: 0.5 }}>No panelists yet. Pick members from the voter roll, or appoint an outside person.</p>
          )}
          <ScrollList maxHeight="60vh">
            {data.panel.map((p) => (
              <div key={p.panel_member_id} style={{ ...rowCard, flexDirection: 'column', alignItems: 'stretch', gap: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
                  <div style={{ minWidth: 0, flex: '1 1 200px' }}>
                    <b style={{ color: 'var(--text-color)' }}>{p.full_name}</b>
                    <span style={badge}>{p.is_member ? 'Member' : 'External'}</span>
                    {p.is_chair && <span style={badge}>Chairperson</span>}
                    {!p.active && <span style={{ ...badge, color: '#e74c3c', backgroundColor: 'color-mix(in srgb, #e74c3c 15%, transparent)' }}>Inactive</span>}
                    <br />
                    {p.student_id && <><small style={{ opacity: 0.6 }}>{regNo(p.student_id)}</small><br /></>}
                    {!p.student_id && p.affiliation && <><small style={{ opacity: 0.6 }}>{p.affiliation}</small><br /></>}
                    <small style={{ color: 'var(--info)' }}>{p.email}</small>
                    {(p.access_ends_at || p.access_expires_at || p.expires_with_phase) && (
                      <>
                        <br />
                        <small style={{ opacity: 0.6 }}>
                          {p.access_ends_at ? `Access ends ${new Date(p.access_ends_at).toLocaleString()}` : ''}
                          {p.expires_with_phase ? ` (follows the ${p.expires_with_phase} phase${p.access_ends_at ? '' : ', which has no end date yet'})` : ''}
                        </small>
                      </>
                    )}
                    {p.appointment_reason && (
                      <>
                        <br />
                        <small style={{ opacity: 0.6 }}>Reason: {p.appointment_reason}</small>
                      </>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
                    {p.active && <ViewAsButton studentId={p.panel_member_id} role="vetting" />}
                    {p.active && (
                      <button style={redLink} onClick={() => setActive(p, false)}>Deactivate</button>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <button style={ghostBtn} onClick={() => setEditing(editing === p.panel_member_id ? null : p.panel_member_id)}>
                    {editing === p.panel_member_id ? 'Close' : 'Edit'}
                  </button>
                  <button style={ghostBtn} onClick={() => reissue(p)}>Reissue password</button>
                  {!p.active && <button style={greenBtn} onClick={() => setActive(p, true)}>Activate</button>}
                </div>
                {editing === p.panel_member_id && (
                  <PanelistEditor schedule={data}
                    panelist={p}
                    onDone={async (changed) => { setEditing(null); if (changed) await load(); }}
                  />
                )}
              </div>
            ))}
          </ScrollList>
        </div>

        {/* ── Right: add someone (search the roll, like Grant Overseer Access) ── */}
        <div>
          <h4 style={{ ...cardTitle, marginBottom: '5px' }}>Add to the Panel</h4>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <button type="button" style={mode === 'commissioners' ? tabOn : ghostBtn} onClick={() => switchMode('commissioners')}>Commissioners</button>
            <button type="button" style={mode === 'roll' ? tabOn : ghostBtn} onClick={() => switchMode('roll')}>Voter roll</button>
            <button type="button" style={mode === 'external' ? tabOn : ghostBtn} onClick={() => switchMode('external')}>Outside person</button>
          </div>

          {mode === 'commissioners' && !picked && (
            <>
              <input style={{ ...inp, marginBottom: '12px' }}
                placeholder="Search commissioners by name or ID…"
                value={search}
                onChange={(e) => setSearch(e.target.value)} />
              <div style={{ border: '1px solid var(--border-color)', borderRadius: '10px', maxHeight: '400px', overflowY: 'auto' }}>
                {commOptions.length === 0 && (
                  <p style={{ opacity: 0.5, padding: '12px 14px', margin: 0 }}>
                    {commissioners.length === 0
                      ? 'There are no commissioners yet.'
                      : (q ? 'No matching commissioners.' : 'Every commissioner is already on the panel.')}
                  </p>
                )}
                {commOptions.map((c) => (
                  <div key={c.student_id} style={rowCard} className="grant-row">
                    <div>
                      <b style={{ color: 'var(--text-color)' }}>{c.full_name}</b>
                      {c.is_chief_commissioner && <span style={badge}>Chief</span>}
                      <br />
                      <small style={{ opacity: 0.6 }}>{regNo(c.student_id)}</small>
                    </div>
                    <button style={greenBtn} onClick={() => pickVoter(c)}>+ Add to Panel</button>
                  </div>
                ))}
              </div>
            </>
          )}

          {mode === 'roll' && !picked && (
            <>
              <input style={{ ...inp, marginBottom: '12px' }}
                placeholder="Search voters by name or ID…"
                value={search}
                onChange={(e) => setSearch(e.target.value)} />
              <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
                {voters.length === 0 && <p style={{ opacity: 0.5, padding: '12px 14px', margin: 0 }}>The voter roll is not loaded yet.</p>}
                {matches.slice(0, SHOWN).map((v) => (
                  <div key={v.student_id} style={rowCard} className="grant-row">
                    <div>
                      <b style={{ color: 'var(--text-color)' }}>{v.full_name}</b>
                      <br />
                      <small style={{ opacity: 0.6 }}>{regNo(v.student_id)}</small>
                    </div>
                    <button style={greenBtn} onClick={() => pickVoter(v)}>+ Add to Panel</button>
                  </div>
                ))}
                {voters.length > 0 && matches.length === 0 && (
                  <p style={{ opacity: 0.5, padding: '12px 14px', margin: 0 }}>No matching voters.</p>
                )}
              </div>
              {matches.length > SHOWN && <p style={meta}>Showing the first {SHOWN} of {matches.length}. Refine your search to narrow it down.</p>}
            </>
          )}

          {showForm && (
            <form onSubmit={mode === 'commissioners' ? linkCommissioner : addPanelist} style={{ ...card, ...formCol }}>
              {picked ? (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
                  <div>
                    <b style={{ color: 'var(--text-color)' }}>{picked.full_name}</b><span style={badge}>Member</span>
                    <br />
                    <small style={{ opacity: 0.6 }}>{regNo(picked.student_id)}</small>
                  </div>
                  <button type="button" style={redLink} onClick={() => { setPicked(null); setForm(BLANK); }}>Change</button>
                </div>
              ) : (
                <>
                  <input style={inp} placeholder="Full name" required value={form.full_name} onChange={set('full_name')} />
                  <input style={inp} placeholder="Affiliation (e.g. Alumni association)" value={form.affiliation} onChange={set('affiliation')} />
                </>
              )}
              {mode === 'commissioners' ? (
                <>
                  <p style={meta}>No new login: they open the Vetting Panel from a button on their own commissioner screen.</p>
                  <textarea style={{ ...inp, minHeight: 60 }} placeholder="Reason for appointment (required)" required value={form.appointment_reason} onChange={set('appointment_reason')} />
                  <button type="submit" disabled={saving} style={{ ...greenBtn, opacity: saving ? 0.6 : 1 }}>
                    {saving ? 'Adding…' : 'Add to Panel'}
                  </button>
                </>
              ) : (
              <>
              <input style={inp} placeholder="Email" type="email" required value={form.email} onChange={set('email')} />
              <input style={inp} placeholder="Phone (for the temporary password)" required value={form.phone} onChange={set('phone')} />
              <textarea style={{ ...inp, minHeight: 60 }} placeholder="Reason for appointment (required)" required value={form.appointment_reason} onChange={set('appointment_reason')} />
              <label style={labelStyle}>
                Access ends at (date and time){form.is_member ? ' — optional' : ''}
                <input style={inp} type="datetime-local" value={form.access_ends} onChange={set('access_ends')} />
              </label>
              <label style={labelStyle}>
                Or when a timeline phase closes
                <select style={inp} value={form.expires_with_phase} onChange={set('expires_with_phase')}>
                  <option value="">None</option>
                  {PHASE_OPTIONS.map(([k, label]) => (
                    <option key={k} value={k} disabled={!form.is_member && !phaseEnd(data, k)}>{phaseLabel(data, k, label)}</option>
                  ))}
                </select>
              </label>
              {!form.is_member && <p style={meta}>Outside people need one access end. If both are set, the earlier one applies.</p>}
              <button type="submit" disabled={saving} style={{ ...greenBtn, opacity: saving ? 0.6 : 1 }}>
                {saving ? 'Adding…' : 'Add panelist'}
              </button>
              </>
              )}
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

// Change an existing panelist's phone, affiliation or access end without removing and re-adding them.
function PanelistEditor({ panelist, schedule, onDone }) {
  const toast = useToast();
  const [affiliation, setAffiliation] = useState(panelist.affiliation || '');
  const [phone, setPhone] = useState('');
  const [accessEnds, setAccessEnds] = useState('');
  const [phase, setPhase] = useState('');
  const [clearEnd, setClearEnd] = useState(false);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const body = {};
    if (affiliation.trim() !== (panelist.affiliation || '')) body.affiliation = affiliation.trim();
    if (phone.trim()) body.phone = phone.trim();
    if (clearEnd) body.clear_access_end = true;
    else if (accessEnds) body.access_expires_at = new Date(accessEnds).toISOString();
    else if (phase) body.expires_with_phase = phase;
    if (!Object.keys(body).length) return toast('Nothing to change.', { kind: 'error' });
    setSaving(true);
    try {
      await api.patch(`/superadmin/vetting-panel/${panelist.panel_member_id}`, body);
      toast('Panelist updated.');
      await onDone(true);
    } catch (err) {
      toast(err.response?.data?.detail || 'Could not update the panelist.', { kind: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: 10 }}>
      <div style={grid}>
        <input style={inp} placeholder="Affiliation" value={affiliation} onChange={(e) => setAffiliation(e.target.value)} />
        <input style={inp} placeholder="New phone (leave blank to keep)" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <label style={labelStyle}>
          New access end (date and time)
          <input style={inp} type="datetime-local" value={accessEnds} disabled={clearEnd} onChange={(e) => setAccessEnds(e.target.value)} />
        </label>
        <label style={labelStyle}>
          Or when a timeline phase closes
          <select style={inp} value={phase} disabled={clearEnd || Boolean(accessEnds)} onChange={(e) => setPhase(e.target.value)}>
            <option value="">No change</option>
            {PHASE_OPTIONS.map(([k, label]) => (
              <option key={k} value={k} disabled={!panelist.is_member && !phaseEnd(schedule, k)}>{phaseLabel(schedule, k, label)}</option>
            ))}
          </select>
        </label>
      </div>
      {panelist.is_member && (
        <label style={checkRow}>
          <input type="checkbox" checked={clearEnd} onChange={(e) => setClearEnd(e.target.checked)} />
          Remove the access end (members only)
        </label>
      )}
      <p style={meta}>Setting a date replaces a phase-based end, and the other way round. Externals must always keep one.</p>
      <button type="button" style={{ ...greenBtn, marginTop: 6 }} disabled={saving} onClick={save}>
        {saving ? 'Saving…' : 'Save changes'}
      </button>
    </div>
  );
}

const heading  = { margin: '0 0 12px', fontSize: '15px', fontWeight: 600, color: 'var(--text-color)' };
const twoCol   = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' };
const card     = { padding: '20px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--bg-color)' };
const cardTitle = { margin: '0 0 14px', color: 'var(--text-color)', fontSize: '15px', fontWeight: '600' };
const rowCard  = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 14px', borderBottom: '1px solid var(--border-color)', gap: '10px' };
const formCol  = { display: 'flex', flexDirection: 'column', gap: '10px', marginTop: 12 };
const meta     = { fontSize: '12px', opacity: 0.65, marginTop: 2 };
const badge    = { marginLeft: '8px', fontSize: '10px', backgroundColor: 'color-mix(in srgb, var(--info) 20%, transparent)', color: 'var(--info)', padding: '2px 6px', borderRadius: '4px' };
const inp      = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const grid     = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, marginTop: 8 };
const checkRow = { display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, fontSize: '13px' };
const labelStyle = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: '12px' };
const btn      = { padding: '10px 18px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const greenBtn = { ...btn, backgroundColor: 'var(--success)' };
const ghostBtn = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const tabOn    = { ...ghostBtn, borderColor: 'var(--info)', color: 'var(--info)', fontWeight: 'bold' };
const redLink  = { background: 'none', border: 'none', color: '#e74c3c', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const infoBox  = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--info)', marginBottom: 12, fontSize: '13px' };
const warnBox  = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--warning)', marginBottom: 12, fontSize: '13px' };
