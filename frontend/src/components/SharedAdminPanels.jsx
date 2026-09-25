import React, { useEffect, useState, useCallback } from 'react';
import api from '../api';
import FinalReport from './FinalReport';
import { useToast, useConfirm, usePrompt } from './UIFeedback';
import { askEarlyReason } from '../electionControls';
import { Icon } from './icons.jsx';
import { DEFAULT_TZ, parseUtc, browserTz, utcToZonedInput, zonedInputToUtcISO, fmtZoned, tzShort, utcOffsetLabel, zoneList } from '../tz';
import { regNo } from '../regNo';

/*
 * One set of panels, mounted identically in all five dashboards.
 *
 * The audit log and integrity chain used to be reachable only under
 * /superadmin/* — no other role could see either, even read-only. Full
 * transparency was the explicit decision, so these read from the /admin/*
 * endpoints which any valid admin token can reach.
 *
 * Nothing here writes. The only write control in this file is the phase
 * editor inside <Timeline>, which renders solely when canEdit is passed
 * (SuperAdmin), and the exception-grant control, which renders solely when
 * isChief is passed. Overseer gains visibility and no write actions at all,
 * by design.
 */

const PHASE_LABELS = {
  applications: 'Applications',
  vetting: 'Vetting',
  campaign: 'Campaign',
  voting: 'Voting',
  results: 'Results',
};

const STATE_COLORS = {
  active: 'var(--success)',
  upcoming: 'var(--info)',
  closed: 'var(--text-muted)',
  unscheduled: 'var(--warning)',
};

function errText(e, fallback = 'Request failed.') {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map(x => x?.msg || JSON.stringify(x)).join(', ');
  if (typeof d === 'string' && d.trim()) return d;
  return fallback;
}

function countdown(seconds) {
  if (seconds == null || seconds < 0) return null;
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

function fmt(value) {
  if (!value) return '—';
  const d = parseUtc(value);   // backend timestamps are naive UTC; new Date(str) would read them as local
  return d ? d.toLocaleString('en-UG', { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}

/* ══════════════════════ HUMAN-READABLE ACTIVITY LOG ══════════════════════
 * Raw log entries are `action` (a snake_case event name) + `details` (a
 * grab-bag of the exact field names the backend happened to log). Fine for
 * debugging, meaningless to an org admin skimming the log — "is_open: false"
 * or "admin guard 403" tells a normal user nothing about what happened.
 * These two maps translate action -> a plain-English title, and
 * action+details -> a plain-English description of the outcome, for the
 * handful of actions where the raw details are actually cryptic (booleans,
 * paths, counts). Anything not listed falls back to a prettified dump —
 * still readable, just not hand-written. */
const ACTION_TITLES = {
  admin_guard_401: 'Access blocked (not signed in)',
  admin_guard_403: 'Access blocked (no permission)',
  admin_login_locked: 'Admin login locked',
  otp_verify_locked: 'Voter verification locked',
  otp_verified: 'Voter code verified',
  vote_cast: 'Ballot cast',
  application_submitted: 'Application submitted',
  application_approved: 'Application approved',
  application_denied: 'Application denied',
  application_force_approved: 'Application force-approved',
  application_force_denied: 'Application force-denied',
  application_vote_cast: 'Commission vote cast',
  candidate_removal_vote: 'Candidate removal vote cast',
  application_finance_cleared: 'Application finance-cleared',
  application_force_finance_cleared: 'Application force finance-cleared',
  it_admin_login: 'IT Admin logged in',
  financial_controller_login: 'Financial Controller logged in',
  overseer_login: 'Overseer logged in',
  commissioner_login: 'Commissioner logged in',
  admin_logout: 'Logged out',
  election_toggled: 'Election toggled',
  election_scheduled: 'Election schedule set',
  election_schedule_cleared: 'Election schedule cleared',
  election_reset: 'Election reset',
  results_certified: 'Certification status changed',
  sms_test_sent: 'Test SMS sent',
  voters_imported: 'Voters imported',
  admin_image_uploaded: 'Image uploaded',
  it_admin_password_changed: 'IT Admin changed password',
  financial_controller_password_changed: 'Financial Controller changed password',
  overseer_password_changed: 'Overseer changed password',
  commissioner_password_changed: 'Commissioner changed password',
  candidate_added: 'Candidate added',
  candidate_updated: 'Candidate edited',
  candidate_deleted: 'Candidate deleted',
  candidate_removed: 'Candidate removed (vote passed)',
  superadmin_mfa_secret_generated: '2FA secret generated',
  organization_created: 'Organisation created',
  branding_updated: 'Branding updated',
  position_added: 'Ballot position added',
  position_deleted: 'Ballot position deleted',
  chief_commissioner_set: 'Chief Commissioner promoted',
  chief_commissioner_cleared: 'Chief Commissioner role removed',
  finance_commissioner_set: 'Finance-clearing power granted',
  finance_commissioner_cleared: 'Finance-clearing power removed',
  commissioner_role_set: 'Commission role set',
  commissioner_toggled: 'Commission access changed',
  it_admin_credentials_set: 'IT Admin credentials set',
  student_add_requested: 'Roster addition requested',
  it_admin_password_reset: 'IT Admin password reset',
  commissioner_password_reset: 'Commissioner password reset',
  student_remove_requested: 'Roster removal requested',
  student_change_cancelled: 'Roster change cancelled',
  student_change_approved: 'Roster change approved',
  student_change_denied: 'Roster change denied',
  it_admin_toggled: 'IT Admin access changed',
  commissioner_credentials_set: 'Commissioner credentials set',
  financial_controller_toggled: 'Financial Controller access changed',
  financial_controller_credentials_set: 'Financial Controller credentials set',
  financial_controller_password_reset: 'Financial Controller password reset',
  overseer_toggled: 'Overseer access changed',
  overseer_credentials_set: 'Overseer credentials set',
  overseer_password_reset: 'Overseer password reset',
  student_change_force_approved: 'Roster change force-approved',
  student_change_force_denied: 'Roster change force-denied',
  student_added_by_superadmin: 'Student added directly',
  student_removed_by_superadmin: 'Student removed directly',
  phases_scheduled: 'Election phases scheduled',
  phase_exception_granted: 'Phase exception granted',
  phase_exception_revoked: 'Phase exception revoked',
  phase_exception_used: 'Phase exception used',
  audit_chain_verified: 'Audit chain verified',
  audit_checkpoint_created: 'Audit checkpoint created',
  audit_checkpoint_anchor_failed: 'Audit checkpoint anchor failed',
  official_report_generated: 'Official document generated',
};

// Label for the page/action someone tried (and failed) to reach, derived
// directly from the backend's route table (main.py) — not guessed. Ordered
// most-specific first since some prefixes nest inside others
// (e.g. /superadmin/commissioners/{id}/set-chief vs plain /superadmin/commissioners).
const PATH_LABELS = [
  [/^\/superadmin\/mfa\/generate/, 'the 2FA setup'],
  [/^\/superadmin\/orgs/, 'the Organisations page'],
  [/^\/superadmin\/branding/, 'Branding settings'],
  [/^\/superadmin\/commissioners\/[^/]+\/set-chief/, 'promoting a Chief Commissioner'],
  [/^\/superadmin\/commissioners\/[^/]+\/clear-chief/, 'removing a Chief Commissioner'],
  [/^\/superadmin\/chief-commissioner/, 'Chief Commissioner info'],
  [/^\/superadmin\/commissioners\/[^/]+\/set-finance-commissioner/, 'granting finance-clearing power'],
  [/^\/superadmin\/commissioners\/[^/]+\/clear-finance-commissioner/, 'removing finance-clearing power'],
  [/^\/superadmin\/finance-commissioner/, 'Finance Commissioner info'],
  [/^\/superadmin\/commissioners\/[^/]+\/set-role/, 'setting a Commission role'],
  [/^\/superadmin\/commissioners\/[^/]+\/toggle/, 'toggling Commission access'],
  [/^\/superadmin\/commissioners\/[^/]+\/set-credentials/, 'setting Commissioner credentials'],
  [/^\/superadmin\/commissioners\/[^/]+\/reset-password/, "resetting a Commissioner's password"],
  [/^\/superadmin\/commissioners\/?$/, 'the Commissioners list'],
  [/^\/superadmin\/it-admins\/[^/]+\/set-credentials/, 'setting IT Admin credentials'],
  [/^\/superadmin\/it-admins\/[^/]+\/reset-password/, "resetting an IT Admin's password"],
  [/^\/superadmin\/it-admins\/[^/]+\/toggle/, 'toggling IT Admin access'],
  [/^\/superadmin\/it-admins\/?$/, 'the IT Admins list'],
  [/^\/superadmin\/financial-controllers\/[^/]+\/toggle/, 'toggling Financial Controller access'],
  [/^\/superadmin\/financial-controllers\/[^/]+\/set-credentials/, 'setting Financial Controller credentials'],
  [/^\/superadmin\/financial-controllers\/[^/]+\/reset-password/, "resetting a Financial Controller's password"],
  [/^\/superadmin\/financial-controllers\/?$/, 'the Financial Controllers list'],
  [/^\/superadmin\/overseers\/[^/]+\/toggle/, 'toggling Overseer access'],
  [/^\/superadmin\/overseers\/[^/]+\/set-credentials/, 'setting Overseer credentials'],
  [/^\/superadmin\/overseers\/[^/]+\/reset-password/, "resetting an Overseer's password"],
  [/^\/superadmin\/overseers\/?$/, 'the Overseers list'],
  [/^\/superadmin\/applications\/[^/]+\/force-approve/, 'force-approving an application'],
  [/^\/superadmin\/applications\/[^/]+\/force-deny/, 'force-denying an application'],
  [/^\/superadmin\/applications\/[^/]+\/force-finance-clear/, 'force finance-clearing an application'],
  [/^\/superadmin\/candidates\/[^/]+\/remove/, 'force-removing a candidate'],
  [/^\/superadmin\/student-changes\/[^/]+\/force-approve/, 'force-approving a roster change'],
  [/^\/superadmin\/student-changes\/[^/]+\/force-deny/, 'force-denying a roster change'],
  [/^\/superadmin\/student-changes\/?$/, 'the roster changes list'],
  [/^\/superadmin\/students\/add/, 'adding a student directly'],
  [/^\/superadmin\/students\/remove/, 'removing a student directly'],
  [/^\/superadmin\/audit\/checkpoint/, 'creating an audit checkpoint'],
  [/^\/superadmin\/audit\/verify/, 'verifying the audit chain'],
  [/^\/superadmin\/audit-log/, 'the (superadmin) audit log'],
  // /admin/* — reachable by any admin token, so these only ever show up in
  // admin_guard_401 (expired/missing session), never admin_guard_403.
  [/^\/admin\/toggle-election/, 'starting or stopping the election'],
  [/^\/admin\/schedule-election/, 'the election schedule'],
  [/^\/admin\/reset-election/, 'resetting the election'],
  [/^\/admin\/toggle-certification/, 'certifying results'],
  [/^\/admin\/import-voters/, 'importing voters'],
  [/^\/admin\/upload-image/, 'uploading an image'],
  [/^\/admin\/applications/, 'the Applications tab'],
  [/^\/admin\/commissioners/, 'the Commission tab'],
  [/^\/admin\/student-changes/, 'the roster changes tab'],
  [/^\/admin\/schedule/, 'the Timeline tab'],
  [/^\/admin\/exception-grants/, 'exception grants'],
  [/^\/admin\/audit-log/, 'the Activity Log'],
  [/^\/admin\/audit/, 'the Chain Verify tab'],
  [/^\/admin\/analytics/, 'the Analytics tab'],
  [/^\/admin\/official-report/, 'the Official Document'],
  [/^\/admin\/set-password/, 'changing password'],
];

function describePath(path) {
  if (!path) return 'a restricted page';
  const hit = PATH_LABELS.find(([re]) => re.test(path));
  return hit ? hit[1] : path;
}

const DETAIL_DESCRIBERS = {
  election_toggled: d => d.is_open
    ? 'Voting opened — election started'
    : (d.early_stop ? `Voting closed EARLY, before the window ended — reason: ${d.reason}` : 'Voting closed — election stopped'),
  results_certified: d => d.is_certified ? 'Marked as officially certified' : 'Certification revoked (back to provisional)',
  it_admin_toggled: d => d.is_active === false ? 'Account deactivated' : 'Account activated',
  commissioner_toggled: d => d.is_commissioner === false ? 'Commission access removed' : 'Commission access granted',
  financial_controller_toggled: d => d.is_financial_controller === false ? 'Access removed' : 'Access granted',
  overseer_toggled: d => d.is_overseer === false ? 'Access removed' : 'Access granted',
  admin_guard_403: d => `Tried to open ${describePath(d.path)}${d.role ? ` while signed in as ${d.role}` : ''} — not allowed`,
  admin_guard_401: d => `Tried to open ${describePath(d.path)} without being signed in`,
  voters_imported: d => d.count != null ? `${d.count} voter(s) added to the roster` : 'Voter roster imported',
  sms_test_sent: d => d.phone ? `Sent to ${d.phone}` : 'Test message sent',
  election_reset: () => 'Election data wiped back to a fresh state',
  vote_cast: d => d.positions ? `Ballot cast (${d.positions} position${d.positions === 1 ? '' : 's'})` : 'Ballot cast',
  // The URL is intentionally not logged (see backend) — this describer only
  // ever needs to handle the byte count now, but stays defensive in case an
  // older log entry from before this fix still has a url on it.
  admin_image_uploaded: d => {
    const kb = d.bytes ? `${(d.bytes / 1024).toFixed(1)} KB` : null;
    return kb ? `Image uploaded (${kb})` : 'Image uploaded';
  },
  phases_scheduled: d => {
    const phases = d.phases || {};
    const names = Object.keys(phases);
    if (!names.length) return 'Phase schedule updated';
    const summary = names
      .map(name => `${PHASE_LABELS[name] || name}: ${phases[name]?.enforced ? 'enforced' : 'not enforced'}`)
      .join(' · ');
    return d.early_end ? `Voting window closed EARLY by this change — reason: ${d.reason} (${summary})` : summary;
  },
  // Was dumping every changed field's full old→new pair (and, before the
  // backend was fixed to only log real changes, unchanged fields too) —
  // unreadable once more than a couple of settings changed at once. Just
  // name what changed; the security-settings screen is where you'd go to
  // see the actual before/after values.
  security_settings_changed: d => {
    const keys = Object.keys(d.changes || {});
    if (!keys.length) return d.reason ? `No effective change — reason: ${d.reason}` : 'No effective change';
    const list = keys.map(k => k.replace(/_/g, ' ')).join(', ');
    return `${keys.length} setting${keys.length === 1 ? '' : 's'} changed (${list})${d.reason ? ` — reason: ${d.reason}` : ''}`;
  },
};

// Keys that are internal bookkeeping rather than something a reader needs —
// dropped from the generic fallback dump so it doesn't drown the one or two
// details that actually matter.
const DETAIL_NOISE_KEYS = new Set(['org_id', 'chain_valid']);

function prettyDetailValue(v) {
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (v === null || v === undefined || v === '') return '—';
  if (Array.isArray(v)) return v.length ? v.map(prettyDetailValue).join(', ') : '—';
  // Generic fallback only ever needs to handle primitives — a nested object
  // here (String(v) => "[object Object]") means some action logs a
  // structured value and deserves its own DETAIL_DESCRIBERS entry, same as
  // phases_scheduled below. Render its keys rather than showing junk.
  if (typeof v === 'object') {
    const inner = Object.entries(v)
      .map(([k, val]) => `${k.replace(/_/g, ' ')}: ${prettyDetailValue(val)}`)
      .join(', ');
    return inner || '—';
  }
  return String(v);
}

function describeDetails(action, details) {
  const special = DETAIL_DESCRIBERS[action];
  if (special) return special(details || {});
  const entries = Object.entries(details || {}).filter(([k]) => !DETAIL_NOISE_KEYS.has(k));
  if (!entries.length) return '—';
  return entries
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${prettyDetailValue(v)}`)
    .join(' · ');
}

function describeAction(action) {
  return ACTION_TITLES[action] || String(action).replace(/_/g, ' ');
}


/* ══════════════════════════ TIMELINE ══════════════════════════ */

export function Timeline({ canEdit = false, isChief = false }) {
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({});
  const [tzDraft, setTzDraft] = useState(DEFAULT_TZ);
  // True the moment the admin touches a field below, so the background poll (every 30s) never
  // yanks a date, checkbox or timezone out from under them mid-edit. Cleared on save/discard,
  // or when the form hasn't been touched yet (so the very first load still populates it).
  const [dirty, setDirty] = useState(false);
  const [grants, setGrants] = useState([]);
  const [grantForm, setGrantForm] = useState({ student_id: '', phase: 'applications', reason: '', expires_at: '' });

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/schedule');
      setData(res.data);
      // The live countdown/status above always refreshes. The editable fields only get
      // reseeded when there's nothing unsaved to lose — otherwise a background poll would
      // silently discard whatever the admin is in the middle of typing or ticking.
      setDirty(prevDirty => {
        if (!prevDirty) {
          const tz = res.data.timezone || DEFAULT_TZ;
          setTzDraft(tz);
          setDraft(Object.fromEntries(res.data.phases.map(p => [
            p.name, { start: utcToZonedInput(p.start, tz), end: utcToZonedInput(p.end, tz), enforced: p.enforced },
          ])));
        }
        return prevDirty;
      });
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load the schedule.'));
    }
  }, []);

  const loadGrants = useCallback(async () => {
    try {
      const res = await api.get('/admin/exception-grants');
      setGrants(res.data || []);
    } catch { /* non-fatal: the panel still shows the timeline */ }
  }, []);

  useEffect(() => {
    load();
    loadGrants();
    // Re-fetch rather than counting down locally off a stale clock, so the
    // countdown stays anchored to server time.
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load, loadGrants]);

  const saveSchedule = async () => {
    // Read the times back in the election timezone (and UTC) before saving, so a wrong zone is obvious.
    const lines = Object.entries(draft).filter(([, w]) => w.start || w.end).map(([name, w]) =>
      `${PHASE_LABELS[name]}: ${w.start ? fmtZoned(zonedInputToUtcISO(w.start, tzDraft), tzDraft) : '—'} → ${w.end ? fmtZoned(zonedInputToUtcISO(w.end, tzDraft), tzDraft) : '—'}`);
    const here = browserTz();
    const ok = await confirm(
      <div style={{ textAlign: 'left', fontSize: 13, lineHeight: 1.6 }}>
        <b>All times are in {tzDraft} ({utcOffsetLabel(tzDraft)}).</b>
        {here !== tzDraft && <p style={{ margin: '6px 0', color: 'var(--warning)' }}><Icon name="warning" /> Your device is set to {here} ({utcOffsetLabel(here)}). The times below are what voters in {tzDraft} will experience.</p>}
        {lines.map(l => <div key={l}>{l}</div>)}
      </div>,
      { confirmText: 'Save schedule' });
    if (!ok) return;
    setSaving(true);
    try {
      const phases = {};
      Object.entries(draft).forEach(([name, w]) => {
        phases[name] = {
          start: zonedInputToUtcISO(w.start, tzDraft),
          end: zonedInputToUtcISO(w.end, tzDraft),
          enforced: Boolean(w.enforced),
        };
      });
      const payload = { phases, round_id: data?.round_id || 'round-1', timezone: tzDraft };
      try {
        await api.post('/admin/schedule/phases', payload);
      } catch (e) {
        // The server says this edit closes a live voting window: ask why, then retry with the reason.
        const d = e?.response?.data?.detail;
        if (e?.response?.status !== 409 || d?.code !== 'early_end_reason_required') throw e;
        const reason = await askEarlyReason(
          d, prompt,
          'This change closes the voting window while it is still open (it was due to close {ends}).\nEnding voting early affects everyone.',
          'Save schedule',
        );
        if (reason == null) return;   // cancelled — nothing saved
        await api.post('/admin/schedule/phases', { ...payload, reason });
      }
      setDirty(false);   // saved — the next poll may now resync the form, e.g. after a co-admin's edit
      await load();
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not save the schedule.'));
    } finally {
      setSaving(false);
    }
  };

  const grantException = async (e) => {
    e.preventDefault();
    if (!grantForm.reason.trim()) return;
    try {
      await api.post('/admin/exception-grants', {
        student_id: grantForm.student_id,
        phase: grantForm.phase,
        reason: grantForm.reason,
        expires_at: zonedInputToUtcISO(grantForm.expires_at, tz),
      });
      setGrantForm({ student_id: '', phase: 'applications', reason: '', expires_at: '' });
      loadGrants();
    } catch (err) {
      toast(errText(err, 'Could not create the grant.'), { kind: 'error' });
    }
  };

  const revoke = async (id) => {
    if (!(await confirm('Revoke this exception grant?', { danger: true, confirmText: 'Revoke' }))) return;
    try {
      await api.post(`/admin/exception-grants/${id}/revoke`);
      loadGrants();
    } catch (err) {
      toast(errText(err, 'Could not revoke.'), { kind: 'error' });
    }
  };

  if (error && !data) return <p style={errStyle}>{error}</p>;
  if (!data) return <p style={mutedStyle}>Loading schedule…</p>;
  const tz = data.timezone || DEFAULT_TZ;

  return (
    <div>
      <h4 style={panelTitle}>Election Timeline <span style={roundPill}>{data.round_id}</span></h4>
      <p style={{ ...mutedStyle, marginTop: 0 }}>
        All times below are shown in <b>{tz}</b> ({tzShort(tz)}, {utcOffsetLabel(tz)}).
        Now: <b>{fmtZoned(data.server_time, tz)}</b>
        {browserTz() !== tz && <> · your device is in {browserTz()} ({utcOffsetLabel(browserTz())})</>}
      </p>

      <div style={phaseGrid}>
        {data.phases.map(p => (
          <div key={p.name} style={{ ...phaseCard, borderLeft: `4px solid ${STATE_COLORS[p.state]}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
              <strong style={{ fontSize: '13px' }}>{PHASE_LABELS[p.name]}</strong>
              <span style={{ ...statePill, color: STATE_COLORS[p.state] }}>{p.state}</span>
            </div>
            <p style={phaseMeta}>Opens: {fmtZoned(p.start, tz)}</p>
            <p style={phaseMeta}>Closes: {fmtZoned(p.end, tz)}</p>
            {p.state === 'upcoming' && p.seconds_until_start != null && (
              <p style={countdownStyle}>Opens in {countdown(p.seconds_until_start)}</p>
            )}
            {p.state === 'active' && p.seconds_until_end != null && (
              <p style={countdownStyle}>Closes in {countdown(p.seconds_until_end)}</p>
            )}
            <p style={{ ...phaseMeta, opacity: 0.6 }}>
              {p.enforced ? <>Enforced — closed means blocked</> : <>Advisory only — not enforced</>}
            </p>
          </div>
        ))}
      </div>

      {canEdit && (
        <div style={{ ...panel, marginTop: '16px' }} className="card-pad">
          <h4 style={panelTitle}>Edit Phase Schedule</h4>
          <label style={{ display: 'block', fontSize: '12px', margin: '0 0 10px' }}>
            <span style={{ opacity: 0.7, fontWeight: 600 }}>Election timezone — the times you type below are in this zone</span>
            <select style={{ ...inputStyle, marginTop: 4, maxWidth: 360 }} value={tzDraft}
              onChange={e => {
                // Same instants, re-expressed in the new zone, so switching zones never silently moves the election.
                const next = e.target.value;
                setDirty(true);
                setDraft(Object.fromEntries(Object.entries(draft).map(([n, w]) => [n, {
                  ...w, start: utcToZonedInput(zonedInputToUtcISO(w.start, tzDraft), next),
                  end: utcToZonedInput(zonedInputToUtcISO(w.end, tzDraft), next),
                }])));
                setTzDraft(next);
              }}>
              {[...new Set([DEFAULT_TZ, tz, ...zoneList()])].map(z => <option key={z} value={z}>{z} ({utcOffsetLabel(z)})</option>)}
            </select>
          </label>
          <p style={mutedStyle}>
            A phase with no times set, or with enforcement off, behaves exactly as the system
            did before phases existed. Turning enforcement on blocks the action outright once
            the window closes.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '14px' }}>
            {data.phases.map(p => {
              const setField = (k, v) => { setDirty(true); setDraft({ ...draft, [p.name]: { ...draft[p.name], [k]: v } }); };
              return (
                <div key={p.name} style={phaseCard}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                    <strong style={{ fontSize: '13px' }}>{PHASE_LABELS[p.name]}</strong>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', margin: 0, cursor: 'pointer', color: 'var(--text-muted)' }}>
                      <input type="checkbox" style={{ width: '18px', height: '18px', margin: 0 }}
                        checked={Boolean(draft[p.name]?.enforced)}
                        onChange={e => setField('enforced', e.target.checked)} />
                      Enforce
                    </label>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '10px' }}>
                    <label style={{ display: 'block', margin: 0, minWidth: 0 }}>
                      <span style={fieldLabel}>Start</span>
                      <input type="datetime-local" style={inputStyle}
                        value={draft[p.name]?.start || ''}
                        onChange={e => setField('start', e.target.value)} />
                    </label>
                    <label style={{ display: 'block', margin: 0, minWidth: 0 }}>
                      <span style={fieldLabel}>End</span>
                      <input type="datetime-local" style={inputStyle}
                        value={draft[p.name]?.end || ''}
                        onChange={e => setField('end', e.target.value)} />
                    </label>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <button style={primaryBtn} onClick={saveSchedule} disabled={saving}>
              {saving ? 'Saving…' : 'Save Schedule'}
            </button>
            {dirty && (
              <>
                <span style={{ fontSize: '12px', color: 'var(--warning)' }}>
                  Unsaved changes — not overwritten by the automatic refresh
                </span>
                <button type="button" style={{ ...ghostBtn, fontSize: '12px', padding: '6px 12px' }}
                  onClick={() => { setDirty(false); load(); }}>
                  Discard &amp; reload
                </button>
              </>
            )}
          </div>
          {error && <p style={errStyle}>{error}</p>}
        </div>
      )}

      {isChief && (
        <div style={{ ...panel, marginTop: '16px' }} className="card-pad">
          <h4 style={panelTitle}>Grant a Phase Exception</h4>
          <p style={mutedStyle}>
            Scoped to one named student, with a written reason, and logged. This is
            deliberately not a "reopen the phase" switch — a blanket reopen would let
            everyone back in and leave no record of who used the window.
          </p>
          <form onSubmit={grantException} style={formCol}>
            <input style={inputStyle} placeholder="Student ID" required
              value={grantForm.student_id}
              onChange={e => setGrantForm({ ...grantForm, student_id: e.target.value })} />
            <select style={inputStyle} value={grantForm.phase}
              aria-label="Phase"
              onChange={e => setGrantForm({ ...grantForm, phase: e.target.value })}>
              {Object.entries(PHASE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <textarea style={{ ...inputStyle, minHeight: '70px' }} required
              placeholder="Reason (required — this is the decision record)"
              value={grantForm.reason}
              onChange={e => setGrantForm({ ...grantForm, reason: e.target.value })} />
            <label style={mutedStyle}>Expires (optional)</label>
            <input type="datetime-local" style={inputStyle} value={grantForm.expires_at}
              onChange={e => setGrantForm({ ...grantForm, expires_at: e.target.value })} />
            <button style={primaryBtn} type="submit">Grant Exception</button>
          </form>
        </div>
      )}

      {grants.length > 0 && (
        <div style={{ ...panel, marginTop: '16px' }} className="card-pad">
          <h4 style={panelTitle}>Exception Grants ({grants.length})</h4>
          <div className="table-scroll" style={{ maxHeight: '50vh', overflowY: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>{[['Student', '18%'], ['Phase', '12%'], ['Reason', '32%'], ['By', '16%'], ['Expires', '16%'], ['', '6%']]
                  .map(([h, w]) => <th key={h || 'actions'} style={{ ...thStyle, width: w }}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {grants.map(g => (
                  <tr key={g._id} style={{ opacity: g.revoked ? 0.4 : 1 }}>
                    <td style={tdStyle}>{g.full_name || regNo(g.student_id)}</td>
                    <td style={tdStyle}>{PHASE_LABELS[g.phase] || g.phase}</td>
                    <td style={tdStyle}>{g.reason}</td>
                    <td style={tdStyle}>{g.granted_by}</td>
                    <td style={tdStyle}>{g.expires_at ? fmt(g.expires_at) : 'No expiry'}</td>
                    <td style={tdStyle}>
                      {isChief && !g.revoked && (
                        <button style={linkBtn} onClick={() => revoke(g._id)}>Revoke</button>
                      )}
                      {g.revoked && <span style={mutedStyle}>Revoked</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════ ELECTION ROADMAP (independent of Timeline) ══════════════════════ */
// Deliberately its own component, its own load/save cycle, and its own tab —
// not a sub-panel of <Timeline>. The 4 phases above gate real behaviour
// (voting open/closed etc.); the roadmap is a free-text, week-grouped
// milestone list (e.g. a client's own printed election calendar) that is
// purely informational and can be edited without touching phase dates at
// all. Backed by GET/POST /admin/roadmap — a separate settings document
// from election_phases.

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

function emptyMilestone() {
  return { mode: 'single', start_date: '', end_date: '', date_label: '', activities: [''] };
}

export function RoadmapEditor({ canEdit = false }) {
  const toast = useToast();
  const [rows, setRows] = useState(null);
  const [weekStartDay, setWeekStartDay] = useState(1);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/roadmap');
      const loaded = (res.data.milestones || []).map(m => ({
        mode: m.end_date ? 'range' : 'single',
        start_date: m.start_date || '',
        end_date: m.end_date || '',
        date_label: m.date_label || '', // legacy free-text rows only
        activities: m.activities && m.activities.length ? m.activities : [''],
      }));
      setRows(loaded.length ? loaded : [emptyMilestone()]);
      setWeekStartDay(Number.isInteger(res.data.week_start_day) ? res.data.week_start_day : 1);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load the roadmap.'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const setRow = (i, patch) => setRows(rs => rs.map((r, idx) => idx === i ? { ...r, ...patch } : r));
  const setActivity = (i, j, val) => setRows(rs => rs.map((r, idx) =>
    idx === i ? { ...r, activities: r.activities.map((a, k) => k === j ? val : a) } : r));
  const addActivity = (i) => setRow(i, { activities: [...rows[i].activities, ''] });
  const removeActivity = (i, j) => setRow(i, { activities: rows[i].activities.filter((_, k) => k !== j) });
  const addRow = () => setRows(rs => [...rs, emptyMilestone()]);
  const removeRow = (i) => setRows(rs => rs.filter((_, idx) => idx !== i));
  const moveRow = (i, dir) => setRows(rs => {
    const next = [...rs];
    const j = i + dir;
    if (j < 0 || j >= next.length) return rs;
    [next[i], next[j]] = [next[j], next[i]];
    return next;
  });

  const save = async () => {
    setSaving(true);
    try {
      const bad = rows.findIndex(r => r.mode === 'range' && r.start_date && r.end_date && r.end_date < r.start_date);
      if (bad !== -1) {
        setError(`Row ${bad + 1}: the end date can't be before the start date.`);
        setSaving(false);
        return;
      }
      const milestones = rows
        .filter(r => r.start_date || r.date_label.trim() || r.activities.some(a => a.trim()))
        .map(r => ({
          start_date: r.start_date || null,
          end_date: r.mode === 'range' && r.end_date && r.end_date !== r.start_date ? r.end_date : null,
          // legacy text is only kept while the row has no picked date
          date_label: r.start_date ? '' : r.date_label,
          activities: r.activities.map(a => a.trim()).filter(Boolean),
        }));
      setError('');
      await api.post('/admin/roadmap', { milestones, week_start_day: weekStartDay });
      await load();
      toast('Roadmap saved.', { kind: 'success' });
    } catch (e) {
      setError(errText(e, 'Could not save the roadmap.'));
    } finally {
      setSaving(false);
    }
  };

  if (error && !rows) return <p style={errStyle}>{error}</p>;
  if (!rows) return <p style={mutedStyle}>Loading roadmap…</p>;

  return (
    <div>
      <h4 style={panelTitle}>Election Roadmap</h4>
      <p style={{ ...mutedStyle, marginTop: 0 }}>
        Free-text milestone list shown to voters under Help → Election Timeline.
        This is independent of the Phase Schedule — it doesn't gate anything,
        it's the printed-style calendar voters see. Both the "Today" highlight
        and the "Week 1, Week 2…" headings are derived automatically by reading
        the dates you pick — Week 1 begins on the earliest event
        date (even mid-week), and later weeks begin on the weekday chosen below.
      </p>

      <label style={{ display: 'block', margin: '0 0 14px', maxWidth: '260px' }}>
        <span style={fieldLabel}>Week starts on</span>
        <select style={inputStyle} disabled={!canEdit} value={weekStartDay}
          onChange={e => setWeekStartDay(parseInt(e.target.value, 10))}>
          {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
        </select>
      </label>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '14px' }}>
        {rows.map((r, i) => (
          <div key={i} style={phaseCard}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
              <strong style={{ fontSize: '13px' }}>Row {i + 1}</strong>
              {canEdit && (
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button style={ghostBtn} onClick={() => moveRow(i, -1)} disabled={i === 0} title="Move up">↑</button>
                  <button style={ghostBtn} onClick={() => moveRow(i, 1)} disabled={i === rows.length - 1} title="Move down">↓</button>
                  <button style={linkBtn} onClick={() => removeRow(i)}>Remove</button>
                </div>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '10px', marginBottom: '10px' }}>
              <div style={{ minWidth: 0 }}>
                <span style={fieldLabel}>Event type</span>
                <div style={{ display: 'flex', gap: '14px', fontSize: '13px', padding: '6px 0' }}>
                  {[['single', 'Single day'], ['range', 'Date range']].map(([val, text]) => (
                    <label key={val} style={{ display: 'flex', alignItems: 'center', gap: '6px', margin: 0 }}>
                      <input type="radio" name={`roadmap-mode-${i}`} disabled={!canEdit}
                        checked={r.mode === val}
                        onChange={() => setRow(i, { mode: val, ...(val === 'single' ? { end_date: '' } : {}) })} />
                      {text}
                    </label>
                  ))}
                </div>
              </div>
              <label style={{ display: 'block', margin: 0, minWidth: 0 }}>
                <span style={fieldLabel}>{r.mode === 'range' ? 'Start date' : 'Date'}</span>
                <input type="date" style={inputStyle} disabled={!canEdit} value={r.start_date}
                  onChange={e => setRow(i, { start_date: e.target.value })} />
              </label>
              {r.mode === 'range' && (
                <label style={{ display: 'block', margin: 0, minWidth: 0 }}>
                  <span style={fieldLabel}>End date</span>
                  <input type="date" style={inputStyle} disabled={!canEdit} value={r.end_date}
                    min={r.start_date || undefined}
                    onChange={e => setRow(i, { end_date: e.target.value })} />
                </label>
              )}
            </div>
            {!r.start_date && r.date_label && (
              <p style={{ ...mutedStyle, margin: '0 0 10px' }}>
                Older text label: "{r.date_label}" — pick a date above to replace it
                (until then it's shown as typed and its dates are read from the text).
              </p>
            )}
            <span style={fieldLabel}>Activities</span>
            {r.activities.map((a, j) => (
              <div key={j} style={{ display: 'flex', gap: '8px', marginBottom: '6px' }}>
                <input style={inputStyle} disabled={!canEdit} placeholder="Activity line"
                  value={a} onChange={e => setActivity(i, j, e.target.value)} />
                {canEdit && r.activities.length > 1 && (
                  <button style={linkBtn} onClick={() => removeActivity(i, j)}>✕</button>
                )}
              </div>
            ))}
            {canEdit && <button style={ghostBtn} onClick={() => addActivity(i)}>+ Add activity</button>}
          </div>
        ))}
      </div>

      {canEdit && (
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button style={ghostBtn} onClick={addRow}>+ Add row</button>
          <button style={primaryBtn} onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save Roadmap'}
          </button>
        </div>
      )}
      {error && <p style={errStyle}>{error}</p>}
    </div>
  );
}

/* ══════════════════════════ ACTIVITY LOG ══════════════════════════ */

export function ActivityLog() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('');
  const [actor, setActor] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (f = filter, a = actor) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (f) params.set('action', f);
      if (a) params.set('actor', a);
      const res = await api.get(`/admin/audit-log?${params.toString()}`);
      setEntries(res.data.entries || []);
      setTotal(res.data.total || 0);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load the activity log.'));
    } finally {
      setLoading(false);
    }
  }, [filter, actor]);

  useEffect(() => { load('', ''); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <h4 style={panelTitle}>Activity Log <span style={roundPill}>{total} entries</span></h4>
      <div style={filterRow} className="stack-mobile">
        <input style={{ ...inputStyle, maxWidth: '260px' }} placeholder="Filter by action…"
          value={filter} onChange={e => setFilter(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()} />
        <input style={{ ...inputStyle, maxWidth: '260px' }} placeholder="Filter by actor…"
          value={actor} onChange={e => setActor(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()} />
        <button style={ghostBtn} onClick={() => load()}>Search</button>
        {(filter || actor) && (
          <button style={ghostBtn} onClick={() => { setFilter(''); setActor(''); load('', ''); }}>Clear</button>
        )}
      </div>

      {error && <p style={errStyle}>{error}</p>}
      {loading && <p style={mutedStyle}>Loading…</p>}

      <div style={scrollBox} className="table-scroll">
        <table style={tableStyle}>
          <thead>
            <tr>{[['When', '17%'], ['Action', '20%'], ['Actor', '18%'], ['Details', '45%']]
              .map(([h, w]) => <th key={h} style={{ ...thStyle, width: w }}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e._id} style={rowStyle}>
                <td style={{ ...tdStyle, fontSize: '11px', opacity: 0.7 }}>
                  {(parseUtc(e.timestamp) || new Date(0)).toLocaleString('en-UG', { dateStyle: 'short', timeStyle: 'short' })}
                </td>
                <td style={{ ...tdStyle, fontWeight: 600 }}>{describeAction(e.action)}</td>
                <td style={{ ...tdStyle, fontSize: '12px' }}>{e.actor}</td>
                <td style={{ ...tdStyle, fontSize: '11px', opacity: 0.75 }}>
                  {describeDetails(e.action, e.details)}
                </td>
              </tr>
            ))}
            {!entries.length && !loading && (
              <tr><td colSpan={4} style={emptyCell}>No log entries found.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ══════════════════════════ CHAIN VERIFY ══════════════════════════ */

export function ChainView() {
  const [checkpoints, setCheckpoints] = useState([]);
  const [anchorFailures, setAnchorFailures] = useState(0);
  const [verdict, setVerdict] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/audit/checkpoints');
      setCheckpoints(res.data.checkpoints || []);
      setAnchorFailures(res.data.anchor_failures || 0);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load checkpoints.'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const verify = async () => {
    setVerifying(true);
    setVerdict(null);
    try {
      const res = await api.get('/admin/audit/verify');
      setVerdict(res.data);
    } catch (e) {
      setError(errText(e, 'Verification failed to run.'));
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div>
      <h4 style={panelTitle}>Integrity Chain</h4>
      <p style={mutedStyle}>
        Every checkpoint is a SHA-256 fold over the ballot events it covers, anchored to
        immutable off-site storage. Verifying re-derives the whole chain from the raw
        events rather than trusting the stored hashes — so the checkpoints either match
        the ballot log or they do not.
      </p>

      <div style={filterRow} className="stack-mobile">
        <button style={primaryBtn} onClick={verify} disabled={verifying}>
          {verifying ? 'Verifying…' : <>Verify Chain</>}
        </button>
        <button style={ghostBtn} onClick={load}>Refresh</button>
      </div>

      {anchorFailures > 0 && (
        <p style={warnBanner}>
          <Icon name="warning" /> {anchorFailures} checkpoint(s) failed to anchor off-site. The local chain is
          intact, but those checkpoints have no external witness.
        </p>
      )}

      {verdict && (
        <div style={verdict.valid ? okBanner : badBanner}>
          {verdict.valid ? (
            <><Icon name="success" /> Chain valid — {verdict.checkpoints_verified} checkpoint(s) re-derived and matched.
              <div className="hash-cell" style={{ fontSize: '11px', marginTop: '6px' }}>
                Head: {verdict.head_hash || '—'}
              </div>
            </>
          ) : (
            <><Icon name="alarm" /> Chain MISMATCH at checkpoint {verdict.first_mismatch_checkpoint_id}.
              <div className="hash-cell" style={{ fontSize: '11px', marginTop: '6px' }}>
                Expected {verdict.expected} · Recomputed {verdict.recomputed}
              </div>
            </>
          )}
        </div>
      )}

      {error && <p style={errStyle}>{error}</p>}

      <div style={scrollBox} className="table-scroll">
        <table style={tableStyle}>
          <thead>
            <tr>{[['Created', '22%'], ['Events', '14%'], ['Chain Hash', '64%']]
              .map(([h, w]) => <th key={h} style={{ ...thStyle, width: w }}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {checkpoints.map(c => (
              <tr key={c.id} style={rowStyle}>
                <td style={{ ...tdStyle, whiteSpace: 'nowrap', fontSize: '11px' }}>{fmt(c.created_at)}</td>
                <td style={{ ...tdStyle, textAlign: 'center' }}>{c.event_count}</td>
                <td style={{ ...tdStyle, fontSize: '10px' }} className="hash-cell">{c.chain_hash}</td>
              </tr>
            ))}
            {!checkpoints.length && (
              <tr><td colSpan={3} style={emptyCell}>No checkpoints recorded yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ══════════════════════════ ANALYTICS ══════════════════════════ */

// Turns a bucket key ("2026-09-17T19:00" for hour, "2026-09-17" for day)
// into a short axis label. Backend sends naive UTC strings — same
// convention as fmt()/toLocalInput() elsewhere in this file — so this is a
// display-only trim, not a timezone conversion.
function bucketLabel(bucket, bucketType, includeDate) {
  if (!bucket) return '';
  if (bucketType === 'day') {
    const [, m, d] = bucket.split('-');
    return `${d}/${m}`;
  }
  const [datePart, timePart] = bucket.split('T');
  const time = timePart ? timePart.slice(0, 5) : bucket;
  // Hourly buckets normally only need the time — but when the series spans
  // more than one calendar day (an election that was toggled open/closed
  // across separate dates, say), showing HH:00 alone loses the date and
  // the x-axis looks like it's jumping backwards (e.g. 20:00 → 17:00) even
  // though the underlying buckets are still in correct chronological order.
  if (!includeDate) return time;
  const [, m, d] = datePart.split('-');
  return `${d}/${m} ${time}`;
}

// Responsive SVG line chart with a value axis (left) and a thinned time
// axis (bottom). Scales via viewBox rather than fixed pixels, so the same
// markup works on a phone and a desktop panel — no separate mobile layout,
// no horizontal scroll, and the x-axis never shows more than ~5 labels
// regardless of how many buckets are in the series.
// A single fixed viewBox ratio is a compromise for every screen size at
// once — 600x220 was only modestly taller on a phone and barely changed on
// desktop. Watching viewport width and picking a genuinely taller ratio
// below 480px means the mobile chart is actually noticeably bigger, not
// just a few px taller, while desktop keeps the wider ratio.
function useIsNarrowViewport(breakpoint = 480) {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < breakpoint
  );
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < breakpoint);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [breakpoint]);
  return narrow;
}

function TurnoutSparkline({ series, bucketType }) {
  const narrow = useIsNarrowViewport();
  // Taller viewBox ratio on phones (600x340 ≈ 1.76:1) vs desktop/tablet
  // (600x220 ≈ 2.73:1) — width:100%/height:auto below derives the actual
  // rendered height straight from this ratio, so this is a real size
  // change, not letterboxing inside a fixed-height box.
  const W = 600, H = narrow ? 340 : 220;
  const padL = 34, padR = 10, padT = 10, padB = 26;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const max = Math.max(1, ...series.map(p => p.votes));
  const n = series.length;
  const x = i => padL + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
  const y = v => padT + plotH - (v / max) * plotH;

  // Detect a multi-day hourly series so labels below can disambiguate —
  // see bucketLabel().
  const spansMultipleDays = bucketType === 'hour' &&
    new Set(series.map(p => p.bucket.split('T')[0])).size > 1;

  const linePoints = series.map((p, i) => `${x(i)},${y(p.votes)}`).join(' ');
  const areaPoints = `${x(0)},${y(0)} ${linePoints} ${x(n - 1)},${y(0)}`;

  // At most 5 x-axis labels: first, last, and evenly spaced ones between —
  // this is what keeps it legible at phone width without a mobile-specific
  // code path.
  const maxLabels = 5;
  const labelStep = Math.max(1, Math.ceil(n / maxLabels));
  const labelIdx = new Set();
  for (let i = 0; i < n; i += labelStep) labelIdx.add(i);
  labelIdx.add(n - 1);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', marginTop: '10px' }} role="img" aria-label="Votes cast over time">
      {/* Y-axis: baseline + peak only, kept sparse on purpose */}
      <line x1={padL} y1={y(0)} x2={W - padR} y2={y(0)} stroke="var(--border-color)" strokeWidth="1" />
      <text x={padL - 6} y={y(0)} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="var(--text-muted)">0</text>
      <text x={padL - 6} y={y(max)} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="var(--text-muted)">{max}</text>
      <line x1={padL} y1={y(max)} x2={W - padR} y2={y(max)} stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="3 3" />

      {/* Filled area + line */}
      <polygon points={areaPoints} fill="var(--info)" opacity="0.12" />
      <polyline points={linePoints} fill="none" stroke="var(--info)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

      {/* Points — <title> gives a hover tooltip on desktop and a tap
          tooltip on most mobile browsers, matching the old bar chart's
          title-attribute behaviour. */}
      {series.map((p, i) => (
        <circle key={p.bucket} cx={x(i)} cy={y(p.votes)} r={n > 40 ? 1.5 : 2.5} fill="var(--info)">
          <title>{`${bucketLabel(p.bucket, bucketType, true)}: ${p.votes} vote(s)`}</title>
        </circle>
      ))}

      {/* X-axis: thinned time labels. The first/last labels anchor to
          start/end instead of middle so their text stays inside the
          viewBox — a middle-anchored label at x=590 (near W=600) had half
          its width running past the edge and getting clipped by the
          panel's overflow. */}
      {series.map((p, i) => labelIdx.has(i) && (
        <text key={p.bucket} x={x(i)} y={H - 8}
          textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
          fontSize="10" fill="var(--text-muted)">
          {bucketLabel(p.bucket, bucketType, spansMultipleDays)}
        </text>
      ))}
    </svg>
  );
}

export function Analytics() {
  const [velocity, setVelocity] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [undervote, setUndervote] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [isOpen, setIsOpen] = useState(true);
  const [bucket, setBucket] = useState('hour');
  const [error, setError] = useState('');

  const load = useCallback(async (b = bucket) => {
    try {
      const [v, f, u, a, o] = await Promise.all([
        api.get(`/admin/analytics/turnout-velocity?bucket=${b}`),
        api.get('/admin/analytics/funnel'),
        api.get('/admin/analytics/undervote'),
        api.get('/admin/analytics/anomalies'),
        api.get('/admin/analytics/overview'),
      ]);
      setVelocity(v.data); setFunnel(f.data); setUndervote(u.data); setAnomalies(a.data);
      setIsOpen(o.data.is_open);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load analytics.'));
    }
  }, [bucket]);

  // load() sets the loading flag before fetching; that is the intended pattern here.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);



  return (
    <div>
      <h4 style={panelTitle}>
        Analytics <span style={roundPill}>{isOpen ? 'Live' : 'Final'}</span>
      </h4>
      {error && <p style={errStyle}>{error}</p>}

      {/* Turnout velocity */}
      <div style={panel} className="card-pad">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: '13px' }}>Turnout Velocity</strong>
          <select style={{ ...inputStyle, width: 'auto' }} value={bucket}
            aria-label="Time bucket"
            onChange={e => { setBucket(e.target.value); load(e.target.value); }}>
            <option value="hour">Per hour</option>
            <option value="day">Per day</option>
          </select>
        </div>
        {velocity?.series?.length ? (
          <>
            <TurnoutSparkline series={velocity.series} bucketType={velocity.bucket} />
            <p style={mutedStyle}>
              {velocity.total_votes} ballots total · peak {velocity.peak?.votes} at{' '}
              {bucketLabel(velocity.peak?.bucket, velocity.bucket, true)}
            </p>
          </>
        ) : <p style={mutedStyle}>No ballots cast yet.</p>}
      </div>

      {/* Funnel */}
      <div style={{ ...panel, marginTop: '14px' }} className="card-pad">
        <strong style={{ fontSize: '13px' }}>Voter Funnel</strong>
        <p style={mutedStyle}>Conversion between stages, not just a count at each.</p>
        {funnel?.steps?.map((s, i) => {
          // The bar width has always been reached/total_registered — a true
          // share of everyone. But the number printed next to it was
          // conversion_from_previous_pct (a stage-to-stage survival rate,
          // trivially 100% for the very first stage). That mismatch is
          // exactly what makes this read as contradictory: a "Completed"
          // bar that's visually a third of the width, labelled "98.4%".
          // Show the number that actually matches the bar (% of all
          // voters), and move the stage-to-stage rate into its own line
          // where it's labelled for what it is.
          const pctOfTotal = funnel.total_registered
            ? Math.round((s.reached / funnel.total_registered) * 1000) / 10
            : 0;
          const prevLabel = i > 0 ? funnel.steps[i - 1].stage.replace(/_/g, ' ') : null;
          return (
            <div key={s.stage} style={{ marginBottom: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                <span style={{ textTransform: 'capitalize' }}>{s.stage.replace(/_/g, ' ')}</span>
                <span>{s.reached} · {pctOfTotal}% of all voters</span>
              </div>
              <div style={barTrack}>
                <div style={{
                  width: `${pctOfTotal}%`,
                  height: '100%', background: 'var(--success)', borderRadius: '4px',
                }} />
              </div>
              {i > 0 && (
                <span style={{ fontSize: '11px', color: s.dropped_off > 0 ? 'var(--danger)' : 'var(--text-muted)' }}>
                  {s.dropped_off > 0
                    ? `${s.dropped_off} dropped off here — ${s.conversion_from_previous_pct}% carried through from ${prevLabel}`
                    : `100% carried through from ${prevLabel}`}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Undervote */}
      <div style={{ ...panel, marginTop: '14px' }} className="card-pad">
        <strong style={{ fontSize: '13px' }}>Per-Position Undervote</strong>
        <p style={mutedStyle}>
          Positions where fewer ballots were cast than there were voters who completed —
          i.e. voters who skipped that race.
        </p>
        {undervote?.positions?.some(p => p.overcounted > 0) && (
          <p style={{ ...mutedStyle, color: 'var(--warning)' }}>
            Votes cast exceed completed voters for one or more positions below — likely
            leftover tallies from a round that was never reset. Numbers here won't be
            reliable until the election is reset or the mismatch is investigated.
          </p>
        )}
        <div className="table-scroll">
          <table style={tableStyle}>
            <thead>
              <tr>{[['Position', '40%'], ['Votes', '20%'], ['Skipped', '20%'], ['Rate', '20%']]
                .map(([h, w]) => <th key={h} style={{ ...thStyle, width: w }}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {undervote?.positions?.map(p => (
                <tr key={p.position} style={rowStyle}>
                  <td style={tdStyle}>{p.position}</td>
                  <td style={{
                    ...tdStyle, textAlign: 'center',
                    color: p.overcounted > 0 ? 'var(--warning)' : undefined,
                  }} title={p.overcounted > 0 ? `${p.overcounted} more than completed voters` : undefined}>
                    {p.votes_cast}{p.overcounted > 0 ? <> <Icon name="warning" /></> : ''}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}>{p.undervotes}</td>
                  <td style={{
                    ...tdStyle, textAlign: 'center', fontWeight: 600,
                    color: p.undervote_rate_pct > 25 ? 'var(--danger)' : 'var(--text-color)',
                  }}>{p.undervote_rate_pct}%</td>
                </tr>
              ))}
              {!undervote?.positions?.length && (
                <tr><td colSpan={4} style={emptyCell}>Nothing to report yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Anomalies */}
      <div style={{ ...panel, marginTop: '14px' }} className="card-pad">
        <strong style={{ fontSize: '13px' }}>Anomalies</strong>
        <p style={mutedStyle}>
          Blocked-access attempts, login and OTP lockouts, off-site anchor failures and
          high-impact actions, pulled out of the general log into one feed.
        </p>
        {anomalies?.summary_24h?.length ? (
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '10px' }}>
            {anomalies.summary_24h.map(s => (
              <span key={s.action} style={anomalyPill}>
                {s.action.replace(/_/g, ' ')}: <strong>{s.count_24h}</strong>
              </span>
            ))}
          </div>
        ) : <p style={mutedStyle}>Nothing flagged in the last 24 hours.</p>}

        <div style={scrollBox} className="table-scroll">
          <table style={tableStyle}>
            <thead>
              <tr>{[['When', '17%'], ['Event', '20%'], ['Actor', '18%'], ['Details', '45%']]
                .map(([h, w]) => <th key={h} style={{ ...thStyle, width: w }}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {anomalies?.events?.map(e => (
                <tr key={e._id} style={rowStyle}>
                  <td style={{ ...tdStyle, fontSize: '11px' }}>
                    {(parseUtc(e.timestamp) || new Date(0)).toLocaleString('en-UG', { dateStyle: 'short', timeStyle: 'short' })}
                  </td>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>{describeAction(e.action)}</td>
                  <td style={{ ...tdStyle, fontSize: '12px' }}>{e.actor}</td>
                  <td style={{ ...tdStyle, fontSize: '11px', opacity: 0.75 }}>
                    {describeDetails(e.action, e.details)}
                  </td>
                </tr>
              ))}
              {!anomalies?.events?.length && (
                <tr><td colSpan={4} style={emptyCell}>No anomalies recorded.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ══════════════ ROSTER STATS (IT Admin landing view) ══════════════ */

export function RosterStats() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await api.get('/admin/analytics/overview');
        if (alive) { setData(res.data); setError(''); }
      } catch (e) {
        if (alive) setError(errText(e, 'Could not load the roster snapshot.'));
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (error) return <p style={errStyle}>{error}</p>;
  if (!data) return <p style={mutedStyle}>Loading…</p>;

  const cards = [
    { label: 'Registered voters', value: data.total_registered },
    { label: 'Ballots cast', value: data.voted },
    { label: 'Turnout', value: `${data.turnout_pct}%` },
    { label: 'Voters with a phone number', value: data.with_phone_on_file },
    { label: 'Candidates', value: data.candidates },
    { label: 'Positions', value: data.positions },
    { label: 'Pending applications', value: data.applications_pending },
    { label: 'Pending roster changes', value: data.student_changes_pending },
  ];

  return (
    <div>
      <h4 style={panelTitle}>
        Roster & Election Snapshot{' '}
        <span style={{ ...roundPill, color: data.is_open ? 'var(--success)' : 'var(--warning)' }}>
          {data.is_open ? 'Voting open' : 'Voting closed'}
          {data.is_certified ? ' · Certified' : ''}
        </span>
      </h4>
      <div style={statGrid}>
        {cards.map(c => (
          <div key={c.label} style={statCard}>
            <div style={{ fontSize: '24px', fontWeight: 800 }}>{c.value}</div>
            <div style={{ fontSize: '11px', opacity: 0.7 }}>{c.label}</div>
          </div>
        ))}
      </div>
      <div style={barTrack}>
        <div style={{ width: `${data.turnout_pct}%`, height: '100%', background: 'var(--success)', borderRadius: '4px' }} />
      </div>
    </div>
  );
}

/* ══════════════ RECENT ACTIVITY (compact overview strip) ══════════════ */

export function RecentActivity({ limit = 6 }) {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await api.get(`/admin/audit-log?limit=${limit}`);
        if (alive) { setEntries(res.data.entries || []); setError(''); }
      } catch (e) {
        if (alive) setError(errText(e, 'Could not load recent activity.'));
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [limit]);

  return (
    <div style={{ marginTop: '20px' }}>
      <h4 style={panelTitle}>Recent Activity</h4>
      {error && <p style={errStyle}>{error}</p>}
      {!error && entries === null && <p style={mutedStyle}>Loading…</p>}
      {!error && entries?.length === 0 && <p style={mutedStyle}>Nothing has happened yet.</p>}
      {!error && entries?.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '65vh', overflowY: 'auto', overscrollBehavior: 'contain' }}>
          {entries.map(e => (
            <div key={e._id} style={{
              display: 'flex', justifyContent: 'space-between', gap: '10px',
              fontSize: '12px', padding: '8px 10px', borderRadius: '8px',
              background: 'var(--card-bg)', border: '1px solid var(--border-color)'
            }}>
              <span>
                <b>{describeAction(e.action)}</b>
                <span style={{ opacity: 0.6 }}> — {describeDetails(e.action, e.details)}</span>
              </span>
              <span style={{ opacity: 0.5, whiteSpace: 'nowrap' }}>
                {(parseUtc(e.timestamp) || new Date(0)).toLocaleString('en-UG', { dateStyle: 'short', timeStyle: 'short' })}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}



export function OfficialCertificationBlock() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get('/admin/official-report');
      setReport(res.data);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not build the official report.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h4 style={panelTitle} className="no-print">Official Certification Document</h4>
      <p style={mutedStyle} className="no-print">
        The sworn declaration, signature grid and distribution list. These are served only
        by an authenticated endpoint — the public results page never receives them, so the
        boundary is what data is fetchable rather than a hidden element.
      </p>

      <div style={filterRow} className="stack-mobile no-print">
        <button style={primaryBtn} onClick={load} disabled={loading}>
          {loading ? 'Building…' : <>Generate Official Document</>}
        </button>
        {report && <button style={ghostBtn} onClick={() => window.print()}>Print</button>}
      </div>

      {error && <p style={errStyle} className="no-print">{error}</p>}

      {report && !report.declaration && (
        <p style={warnBanner} className="no-print">
          The declaration is withheld until results are certified. Certification is the
          Chief Commissioner's action. The tallies below are still shown so you can review
          them ahead of certifying.
        </p>
      )}

      {report && (
        <>
          {/* Same component, same visual structure as the public results PDF
              — declaration and signatories are the only props the public
              path never passes; they add the signed instrument. */}
          <FinalReport
            data={{ results: report.results }}
            totalVotes={report.voter_turnout}
            isElectionOpen={report.is_open}
            isCertified={report.is_certified}
            logoUrl={report.logo_url}
            orgName={report.org_name}
            universityName={report.university_name}
            universityLogoUrl={report.university_logo_url}
            declaration={report.declaration}
            signatories={report.signatories}
            ccList={report.cc_list}
            contactChanges={report.contact_changes}
            rosterLedger={report.roster_ledger}
          />

          {/* Chain/fingerprint provenance — admin-only context, not part of
              the signed instrument's own layout, so it prints as its own
              block rather than living inside FinalReport. */}
          <div style={chainFooter} className="print-only">
            <p style={{ margin: '2px 0' }}>
              Integrity chain:{' '}
              <strong style={{ color: report.chain.valid ? 'var(--success)' : 'var(--danger)' }}>
                {report.chain.valid ? 'VERIFIED' : 'MISMATCH'}
              </strong>{' '}
              ({report.chain.checkpoints_verified} checkpoint(s))
            </p>
            <p style={{ margin: '2px 0' }} className="hash-cell">Fingerprint: {report.fingerprint}</p>
            <p style={{ margin: '2px 0', opacity: 0.7 }}>
              Generated {fmt(report.generated_at)} by {report.generated_by}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

/* ══════════════════════════ SHARED TAB HELPER ══════════════════════════ */

// The tabs every dashboard gets. Keeping the id/label pairs here means a
// future tab is added once, not five times. Roadmap is SuperAdmin-only —
// see ROADMAP_TAB_DEF below — since it lets someone rewrite the phase
// schedule wholesale, not just view it.
// eslint-disable-next-line react-refresh/only-export-components
export const SHARED_TAB_DEFS = [
  { id: 'shared_timeline', label: <>Timeline</> },
  { id: 'shared_analytics', label: <>Analytics</> },
  { id: 'shared_activity', label: <>Activity Log</> },
  { id: 'shared_chain', label: <>Chain Verify</> },
];

// eslint-disable-next-line react-refresh/only-export-components
export const ROADMAP_TAB_DEF = { id: 'shared_roadmap', label: <>Roadmap</> };

export function SharedTabPanels({ activeTab, canEditSchedule = false, isChief = false }) {
  if (activeTab === 'shared_timeline') return <Timeline canEdit={canEditSchedule} isChief={isChief} />;
  if (activeTab === 'shared_roadmap') return <RoadmapEditor canEdit={canEditSchedule} />;
  if (activeTab === 'shared_analytics') return <Analytics />;
  if (activeTab === 'shared_activity') return <ActivityLog />;
  if (activeTab === 'shared_chain') return <ChainView />;
  return null;
}

/* ══════════════════════════ STYLES ══════════════════════════ */

const panel = { padding: '18px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--bg-color)' };
const panelTitle = { margin: '0 0 12px', fontSize: '15px', fontWeight: 600, color: 'var(--text-color)', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' };
const mutedStyle = { fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 10px' };
const errStyle = { fontSize: '12px', color: 'var(--danger)', margin: '8px 0' };
const roundPill = { fontSize: '10px', fontWeight: 700, padding: '3px 8px', borderRadius: '10px', background: 'color-mix(in srgb, var(--info) 18%, transparent)', color: 'var(--info)' };
const statePill = { fontSize: '10px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px' };
const phaseGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px' };
const phaseCard = { ...panel, padding: '14px' };
const fieldLabel = { display: 'block', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.4px', color: 'var(--text-muted)', marginBottom: '4px' };
const phaseMeta = { fontSize: '11px', margin: '4px 0', color: 'var(--text-muted)' };
const countdownStyle = { fontSize: '12px', margin: '6px 0', fontWeight: 700, color: 'var(--info)' };
const filterRow = { display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '12px', alignItems: 'center' };
const formCol = { display: 'flex', flexDirection: 'column', gap: '10px' };
const inputStyle = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const primaryBtn = { padding: '10px 18px', color: '#fff', backgroundColor: 'var(--info)', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 700, fontSize: '13px' };
const ghostBtn = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const linkBtn = { background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontWeight: 700, fontSize: '12px' };
const scrollBox = { maxHeight: '460px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px', marginTop: '10px' };
const tableStyle = { width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed' };
const thStyle = { padding: '10px 12px', textAlign: 'left', fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)', background: 'var(--surface-2)', position: 'sticky', top: 0, zIndex: 2, whiteSpace: 'nowrap' };
const tdStyle = { padding: '10px 12px', color: 'var(--text-color)', fontSize: '13px' };
const rowStyle = { borderBottom: '1px solid var(--border-color)' };
const emptyCell = { ...tdStyle, textAlign: 'center', opacity: 0.45, padding: '28px' };
const barTrack = { width: '100%', height: '8px', background: 'var(--surface-2)', borderRadius: '4px', overflow: 'hidden', marginTop: '6px' };
const statGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px', marginBottom: '14px' };
const statCard = { ...panel, padding: '14px', textAlign: 'center' };
const anomalyPill = { fontSize: '11px', padding: '4px 10px', borderRadius: '10px', background: 'color-mix(in srgb, var(--warning) 18%, transparent)', color: 'var(--warning)', fontWeight: 600 };
const okBanner = { padding: '12px', borderRadius: '8px', background: 'color-mix(in srgb, var(--success) 15%, transparent)', color: 'var(--success)', fontSize: '13px', fontWeight: 600, marginBottom: '10px' };
const badBanner = { padding: '12px', borderRadius: '8px', background: 'color-mix(in srgb, var(--danger) 15%, transparent)', color: 'var(--danger)', fontSize: '13px', fontWeight: 700, marginBottom: '10px' };
const warnBanner = { padding: '12px', borderRadius: '8px', background: 'color-mix(in srgb, var(--warning) 15%, transparent)', color: 'var(--warning)', fontSize: '12px', fontWeight: 600, marginBottom: '10px' };
const chainFooter = { marginTop: '10px', fontSize: '11px', borderTop: '1px dashed #000', paddingTop: '10px', color: '#444' };
