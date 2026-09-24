import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm } from './UIFeedback';
import { Icon } from './icons.jsx';
import { errMsg } from '../studentEdit';
import { DEFAULT_TZ, utcToZonedInput, zonedInputToUtcISO, utcOffsetLabel, fmtZoned } from '../tz';

/** SMS usage tile (read-only; superadmin / overseer / commission). */
export function SmsUsageTile() {
  const [u, setU] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => api.get('/admin/sms-usage').then(r => live && setU(r.data)).catch(() => {});
    load(); const id = setInterval(load, 30000);
    return () => { live = false; clearInterval(id); };
  }, []);
  if (!u) return null;
  const modeColor = { normal: 'var(--success)', conservation: '#e67e22', under_attack: 'var(--danger)' }[u.mode];
  const low = u.budget_pct_left != null && u.budget_pct_left <= 25;
  return (
    <div style={box}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <b style={{ fontSize: 14 }}>SMS budget &amp; delivery</b>
        <span style={{ fontSize: 12, fontWeight: 700, color: modeColor }}>{u.mode.replace('_', ' ').toUpperCase()}</span>
      </div>
      <div style={grid}>
        <Stat label="Sent" value={u.sent_total} />
        <Stat label="Verified" value={u.verified_total} />
        <Stat label="Send→verify" value={u.send_to_verify_ratio == null ? '—' : `${Math.round(u.send_to_verify_ratio * 100)}%`} />
        <Stat label="Last 30 min" value={u.recent.ratio_30m == null ? '—' : `${Math.round(u.recent.ratio_30m * 100)}% of ${u.recent.sends_30m}`} />
        <Stat label="Budget left" value={u.budget_total ? `${u.budget_left} / ${u.budget_total}` : 'not set'} color={low ? 'var(--danger)' : undefined} />
      </div>
      {u.mode === 'under_attack' && <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> Send-to-verify ratio is very low: possible SMS pumping. The bot check is mandatory until it recovers.</p>}
      {u.budget_total && !u.budget_enforced && <p style={note}>Budget is in monitor-only mode (counted and alerted, not enforced).</p>}
      {low && <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> Credit is running low — top up the provider account.</p>}
    </div>
  );
}
const Stat = ({ label, value, color }) => (
  <div><small style={{ opacity: 0.6 }}>{label}</small><div style={{ fontWeight: 700, color }}>{value}</div></div>
);

/** Superadmin: freeze time, target risk, Turnstile, SMS budget, contact-change quotas, break-glass. */
export default function SecurityPanel() {
  const toast = useToast();
  const confirm = useConfirm();
  const [d, setD] = useState(null);
  const [f, setF] = useState({});
  const [budget, setBudget] = useState({ total: '', mode: 'normal', enforce: false });
  const [reason, setReason] = useState('');
  const [ledger, setLedger] = useState(null);
  const [tz, setTz] = useState(DEFAULT_TZ);   // election timezone (set on the Timeline tab)

  const load = useCallback(async () => {
    try {
      const r = (await api.get('/superadmin/security-settings')).data;
      const u = (await api.get('/superadmin/sms-budget')).data;
      const zone = (await api.get('/admin/schedule')).data.timezone || DEFAULT_TZ;
      setTz(zone);
      setD(r);
      setF({ ...r.settings, roster_freeze_at: utcToZonedInput(r.settings.roster_freeze_at, zone) });
      setBudget({ total: u.budget_total ?? '', mode: u.mode === 'conservation' ? 'conservation' : 'normal', enforce: u.budget_enforced });
    } catch (e) { toast(errMsg(e, 'Could not load security settings.'), { kind: 'error' }); }
  }, [toast]);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);
  if (!d) return null;

  const need = () => { if (reason.trim().length < 3) { toast('Enter a reason for this change first.', { kind: 'error' }); return false; } return true; };
  const saveSecurity = async () => {
    if (!need()) return;
    if (!(await confirm('Save these security settings? The change is logged with your reason and shown to the overseer.', { confirmText: 'Save' }))) return;
    const body = { reason: reason.trim() };
    ['roster_freeze_enabled', 'contact_change_required', 'superadmin_breakglass', 'sms_fallback_on_timeout'].forEach(k => { body[k] = Boolean(f[k]); });
    ['otp_target_risk', 'quota_alert_pct', 'quota_hard_cap_pct'].forEach(k => { body[k] = Number(f[k]); });
    ['contact_change_ttl_hours', 'contact_change_max_per_voter', 'approver_daily_cap', 'digest_days',
      'reset_admin_hourly_alert', 'reset_admin_hourly_hard_cap', 'reset_per_voter_daily', 'reset_per_voter_election'].forEach(k => { body[k] = Number(f[k]); });
    body.turnstile_mode = f.turnstile_mode;
    body.public_results_mode = f.public_results_mode;
    body.approval_policy = f.approval_policy;
    if (f.roster_freeze_at) body.roster_freeze_at = zonedInputToUtcISO(f.roster_freeze_at, tz);
    else body.clear_roster_freeze_at = true;
    try { await api.put('/superadmin/security-settings', body); toast('Security settings saved.', { kind: 'success' }); setReason(''); load(); }
    catch (e) { toast(errMsg(e, 'Save failed.'), { kind: 'error' }); }
  };
  const saveBudget = async () => {
    if (!need()) return;
    try {
      await api.put('/superadmin/sms-budget', {
        reason: reason.trim(), sms_budget_total: budget.total === '' ? undefined : Number(budget.total),
        sms_mode: budget.mode, sms_budget_enforce: budget.enforce,
      });
      toast('SMS budget saved.', { kind: 'success' }); setReason(''); load();
    } catch (e) { toast(errMsg(e, 'Save failed.'), { kind: 'error' }); }
  };
  const verifyLedger = async () => {
    try { setLedger((await api.get('/admin/roster-ledger/verify')).data); } catch (e) { toast(errMsg(e, 'Verify failed.'), { kind: 'error' }); }
  };
  const num = (k, label, step = 1) => (
    <label style={fld}><span style={lbl}>{label}</span>
      <input style={inp} type="number" step={step} value={f[k] ?? ''} onChange={e => setF({ ...f, [k]: e.target.value })} /></label>
  );
  const chk = (k, label) => (
    <label style={{ ...fld, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
      <input type="checkbox" checked={Boolean(f[k])} onChange={e => setF({ ...f, [k]: e.target.checked })} /><span style={{ fontSize: 13 }}>{label}</span></label>
  );
  const dv = d.derived;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 720 }}>
      <SmsUsageTile />
      {d.banner && <div style={{ ...box, borderColor: 'var(--warning)' }}><Icon name="warning" /> {d.banner} Schedule the voting phase (Timeline tab) with “enforced” on.</div>}

      <div style={box}>
        <b style={{ fontSize: 14 }}>Lock strength (derived from the voting window)</b>
        <p style={note}>
          Each voter gets {dv.free_guesses} free wrong guesses, then one more every <b>{Math.round(dv.refill_interval_seconds / 60)} min</b>
          {' '}(total budget ≈ {dv.guess_budget} guesses over the window). Changing the window recomputes this automatically.
        </p>
        <div style={grid}>{num('otp_target_risk', 'Target risk ε (per voter)', 0.00001)}</div>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Roster freeze &amp; contact changes</b>
        <p style={note}>Current phase: <b>{d.roster.phase.replace('_', ' ')}</b>. Freeze moment: <b>{fmtZoned(d.roster.freeze_at, tz)}</b> (default = voting start).</p>
        <div style={grid}>
          <label style={fld}><span style={lbl}>Freeze at, in {tz} ({utcOffsetLabel(tz)}) — blank = voting start</span>
            <input style={inp} type="datetime-local" value={f.roster_freeze_at || ''} onChange={e => setF({ ...f, roster_freeze_at: e.target.value })} /></label>
          {num('contact_change_ttl_hours', 'Request expiry (hours)')}
          {num('contact_change_max_per_voter', 'Max approved per voter')}
          {num('approver_daily_cap', 'Approvals per commissioner / day')}
          {num('quota_alert_pct', 'Alert at % of electorate', 0.5)}
          {num('quota_hard_cap_pct', 'Hard stop at % of electorate', 0.5)}
          {num('digest_days', 'Pre-freeze digest (days)')}
        </div>
        {chk('roster_freeze_enabled', 'Roster freeze enabled')}
        {chk('contact_change_required', 'Contact changes require commissioner approval')}
        {chk('superadmin_breakglass', 'Allow superadmin break-glass approval (flagged red in the ledger)')}
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Admin “Reset OTP limits” caps</b>
        <div style={grid}>
          {num('reset_per_voter_daily', 'Per voter / day')}{num('reset_per_voter_election', 'Per voter / election')}
          {num('reset_admin_hourly_alert', 'Per admin / hour: alert')}{num('reset_admin_hourly_hard_cap', 'Per admin / hour: hard stop')}
        </div>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>SMS delivery</b>
        <p style={note}>When EgoSMS times out (result unknown — it may still have been delivered and billed), fall back to MamboSMS automatically. Off by default to avoid double-sending a voter's OTP.</p>
        {chk('sms_fallback_on_timeout', 'Fall back to MamboSMS on an ambiguous EgoSMS timeout')}
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Candidate approval policy</b>
        <p style={note}>How the commission's votes on candidate applications and removals resolve. Changing this immediately re-checks every pending application and pending removal vote against the new rule — it can flip an outcome without a new vote being cast.</p>
        <select style={inp} value={f.approval_policy} onChange={e => setF({ ...f, approval_policy: e.target.value })}>
          <option value="majority_total">Majority of total commissioners (original behavior)</option>
          <option value="unanimous">Unanimous — every commissioner must agree</option>
          <option value="majority_cast">Majority of votes cast — resolves once everyone has voted</option>
        </select>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Public results visibility</b>
        <p style={note}>Controls when the public, unauthenticated results page shows numbers. This is per-org — it does not affect other organizations on this deployment.</p>
        <select style={inp} value={f.public_results_mode} onChange={e => setF({ ...f, public_results_mode: e.target.value })}>
          <option value="live">Live (visible while voting is open — original behavior)</option>
          <option value="closed">Hidden until voting closes</option>
          <option value="certified">Hidden until a commissioner certifies results (recommended)</option>
        </select>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Bot check (Cloudflare Turnstile)</b>
        <select style={inp} value={f.turnstile_mode} onChange={e => setF({ ...f, turnstile_mode: e.target.value })}>
          <option value="off">Off</option><option value="adaptive">Adaptive (suspicious IPs / under attack)</option><option value="on">On (recommended for election day)</option>
        </select>
        {!dv.turnstile_secret_configured && f.turnstile_mode !== 'off' && <p style={{ ...note, color: 'var(--warning)' }}><Icon name="warning" /> TURNSTILE_SECRET is not set on the server, so the check cannot be enforced.</p>}
      </div>

      <label style={fld}><span style={lbl}>Reason for this change (required, logged)</span>
        <input style={inp} value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. election-day hardening" /></label>
      <button style={btn} onClick={saveSecurity}>Save security settings</button>

      <div style={box}>
        <b style={{ fontSize: 14 }}>SMS budget</b>
        <p style={note}>Suggested: <b>{dv.suggested_sms_budget}</b> (voters × 2.5). Raising the budget re-arms the 50/25/10 % alerts.</p>
        <div style={grid}>
          <label style={fld}><span style={lbl}>Budget (SMS)</span><input style={inp} type="number" value={budget.total} onChange={e => setBudget({ ...budget, total: e.target.value })} /></label>
          <label style={fld}><span style={lbl}>Mode</span>
            <select style={inp} value={budget.mode} onChange={e => setBudget({ ...budget, mode: e.target.value })}>
              <option value="normal">Normal</option><option value="conservation">Conservation (last resort: first codes only)</option></select></label>
        </div>
        <label style={{ ...fld, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={budget.enforce} onChange={e => setBudget({ ...budget, enforce: e.target.checked })} />
          <span style={{ fontSize: 13 }}>Enforce (leave off / monitor-only until the dry run passes)</span></label>
        <button style={{ ...btn, marginTop: 8 }} onClick={saveBudget}>Save SMS budget</button>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Roster ledger integrity</b>
        <button style={{ ...btn, background: '#3498db', marginLeft: 10 }} onClick={verifyLedger}>Verify chain</button>
        {ledger && <p style={{ ...note, color: ledger.valid ? 'var(--success)' : 'var(--danger)' }}>
          {ledger.valid ? `VERIFIED — ${ledger.entries} entries` : `MISMATCH at entry #${ledger.first_bad_seq}`}</p>}
      </div>
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--bg-color)' };
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginTop: 10 };
const note = { fontSize: 12, opacity: 0.75, margin: '6px 0' };
const fld = { display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 };
const lbl = { fontSize: 12, opacity: 0.65, fontWeight: 600 };
const inp = { padding: '9px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, width: '100%', boxSizing: 'border-box' };
const btn = { padding: '10px 18px', color: '#fff', background: '#2ecc71', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 'bold', fontSize: 13 };
