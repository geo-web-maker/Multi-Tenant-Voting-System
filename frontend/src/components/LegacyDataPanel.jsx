import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm } from './UIFeedback';
import { Icon } from './icons.jsx';
import { errMsg } from '../studentEdit';

const LABELS = {
  voters: 'Voters / staff', applications: 'Applications', candidates: 'Candidates', positions: 'Positions',
  settings: 'Settings & branding', student_changes: 'Student change requests', contact_changes: 'Contact change requests',
  exception_grants: 'Exception grants', student_edit_audit: 'Student edit history', audit_log: 'Activity log',
  candidate_tokens: 'Candidate status links', certificates: 'Certificates', panel_members: 'Vetting panel members',
  otps: 'Login codes', admin_otps: 'Admin login codes', vote_events: 'Ballots (vote events)',
  audit_checkpoints: 'Ballot integrity checkpoints', roster_ledger: 'Roster ledger',
  sms_usage: 'SMS usage counters', otp_send_state: 'OTP send limits (expire by themselves)',
  otp_guess_state: 'OTP guess limits (expire by themselves)',
};
const CONFIRM_PHRASE = 'DELETE LEGACY DATA';

/**
 * Superadmin: finds leftover documents that belong to NO organization (from before multi-tenancy)
 * so each can be assigned to the right organization or removed. Nothing here runs automatically.
 */
export default function LegacyDataPanel() {
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState(null);
  const [orgs, setOrgs] = useState([]);
  const [picked, setPicked] = useState({});
  const [orgId, setOrgId] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [d, o] = await Promise.all([api.get('/superadmin/legacy-data'), api.get('/superadmin/orgs')]);
      setData(d.data);
      setOrgs(Array.isArray(o.data) ? o.data : []);
      setPicked({});
      setFailed(false);
    } catch (e) { setFailed(true); toast(errMsg(e, 'Could not check for legacy data.'), { kind: 'error' }); }
    finally { setBusy(false); }
  }, [toast]);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);

  const rows = (data?.collections || []).filter(c => c.count > 0);
  const chosen = rows.filter(c => picked[c.name]);
  const chosenNames = chosen.map(c => c.name);
  const cannotAssign = chosen.filter(c => !c.assignable);
  const toggle = (name) => setPicked(p => ({ ...p, [name]: !p[name] }));

  const assign = async () => {
    const org = orgs.find(o => String(o._id) === orgId);
    if (!org) { toast('Choose the organization these records belong to.', { kind: 'error' }); return; }
    if (!chosenNames.length) { toast('Tick at least one item first.', { kind: 'error' }); return; }
    if (cannotAssign.length) { toast(`${cannotAssign.map(c => LABELS[c.name] || c.name).join(', ')} cannot be assigned; remove it or untick it.`, { kind: 'error' }); return; }
    const ok = await confirm(
      `Assign ${chosen.reduce((n, c) => n + c.count, 0)} record(s) to "${org.name}"? They will become part of that organization's data immediately.`,
      { confirmText: 'Assign' });
    if (!ok) return;
    setBusy(true);
    try {
      const r = (await api.post('/superadmin/legacy-data/assign', { org_id: orgId, collections: chosenNames })).data;
      const bad = r.results.filter(x => x.error);
      if (bad.length) toast(`${bad.map(x => LABELS[x.name] || x.name).join(', ')}: ${bad[0].error}`, { kind: 'error' });
      else toast('Assigned.', { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Assign failed.'), { kind: 'error' }); }
    finally { setBusy(false); load(); }
  };

  const remove = async () => {
    if (!chosenNames.length) { toast('Tick at least one item first.', { kind: 'error' }); return; }
    const ok = await confirm(
      `Permanently remove ${chosen.reduce((n, c) => n + c.count, 0)} record(s) that belong to no organization? A safety copy is saved to the backup bucket first; if that fails nothing is deleted.`,
      { danger: true, confirmText: 'Remove', requireText: CONFIRM_PHRASE });
    if (!ok) return;
    setBusy(true);
    try {
      await api.post('/superadmin/legacy-data/delete', { collections: chosenNames, confirm: CONFIRM_PHRASE });
      toast('Removed.', { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Remove failed.'), { kind: 'error' }); }
    finally { setBusy(false); load(); }
  };

  return (
    <div style={{ ...box, gridColumn: '1 / -1' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <b style={{ fontSize: 14 }}>Legacy data check</b>
        <button style={ghost} disabled={busy} onClick={load}>{busy ? 'Checking…' : 'Check again'}</button>
      </div>
      <p style={note}>
        Finds records that belong to no organization (left over from before multi-tenancy). The app no longer reads or writes
        them, so they are invisible to every client. Assign each group to the right organization, or remove it.
      </p>
      {failed && !data && <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> The check could not run.</p>}
      {data && rows.length === 0 && (
        <p style={{ ...note, color: 'var(--success)', fontWeight: 700 }} data-testid="legacy-clean">No legacy data found. Every record belongs to an organization.</p>
      )}
      {rows.length > 0 && (
        <>
          <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> {data.total} record(s) belong to no organization.</p>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6 }}>
            {rows.map(c => (
              <li key={c.name}>
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
                  <input type="checkbox" checked={Boolean(picked[c.name])} onChange={() => toggle(c.name)} />
                  <span>{LABELS[c.name] || c.name}</span>
                  <b>{c.count}</b>
                  {!c.assignable && <small style={{ opacity: 0.65 }}>(remove only)</small>}
                </label>
              </li>
            ))}
          </ul>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12, alignItems: 'center' }}>
            <select aria-label="Organization to assign to" style={inp} value={orgId} onChange={e => setOrgId(e.target.value)}>
              <option value="">Assign to organization…</option>
              {orgs.map(o => <option key={o._id} value={String(o._id)}>{o.name} ({o.slug})</option>)}
            </select>
            <button style={primary} disabled={busy} onClick={assign}>Assign selected</button>
            <button style={danger} disabled={busy} onClick={remove}>Remove selected</button>
          </div>
        </>
      )}
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--bg-color)' };
const note = { fontSize: 12, opacity: 0.8, margin: '6px 0' };
const inp = { padding: '9px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, minWidth: 220 };
const base = { padding: '9px 16px', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 'bold', fontSize: 13, color: 'var(--bp-ai, var(--bg-color))' };
const primary = { ...base, background: 'var(--bp-ok, var(--success))' };
const danger = { ...base, background: 'var(--danger)' };
const ghost = { ...base, background: 'transparent', color: 'var(--text-color)', border: '1px solid var(--border-color)' };
