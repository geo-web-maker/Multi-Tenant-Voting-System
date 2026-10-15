import React, { useCallback, useEffect, useState } from 'react';
import { useIdText } from '../idText';
import api from '../api';
import { startPolling } from '../hooks/usePolling';
import { useToast, useConfirm } from './UIFeedback';
import { Icon } from './icons.jsx';
import { errMsg } from '../studentEdit';
import { turnstileConfigured } from '../supportLink';
import { useRevealReady } from './RevealGroup';
import LegacyDataPanel from './LegacyDataPanel';
import TurnstileWidget from './TurnstileWidget';
import { DEFAULT_TZ, utcToZonedInput, zonedInputToUtcISO, utcOffsetLabel, fmtZoned } from '../tz';

const ROUTE_SHORT = {
  default: 'Automatic', egosms_first: 'EgoSMS → MamboSMS', mambosms_first: 'MamboSMS → EgoSMS',
  egosms_only: 'EgoSMS only', mambosms_only: 'MamboSMS only',
};
/** SMS usage tile (read-only; superadmin / overseer / commission). */
// hideBudgetLeft: the SMS tab shows the budget as its own box, so the tile there leaves it out.
export function SmsUsageTile({ initial = null, hideBudgetLeft = false }) {
  const [u, setU] = useState(initial);
  useEffect(() => {
    let live = true;
    const load = () => api.get('/admin/sms-usage').then(r => live && setU(r.data)).catch(() => {});
    if (initial == null) load();   // parent already fetched it in parallel with the rest of the panel
    const stop = startPolling(load, 30000);
    return () => { live = false; stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `initial` is only the first-render seed
  }, []);
  if (!u) return null;
  const modeColor = { normal: 'var(--success)', conservation: 'var(--bp-wn, #e67e22)', under_attack: 'var(--danger)' }[u.mode];
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
        {!hideBudgetLeft && <Stat label="Budget left" value={u.budget_total ? `${u.budget_left} / ${u.budget_total}` : 'not set'} color={low ? 'var(--danger)' : undefined} />}
      </div>
      {u.sms_route_otp && (
        <p style={note}>Routing — OTP: <b>{ROUTE_SHORT[u.sms_route_otp] || u.sms_route_otp}</b> · Other messages: <b>{ROUTE_SHORT[u.sms_route_other] || u.sms_route_other}</b></p>
      )}
      {u.mode === 'under_attack' && <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> Send-to-verify ratio is very low: possible SMS pumping. The bot check is mandatory until it recovers.</p>}
      {u.budget_total && !u.budget_enforced && <p style={note}>Budget is in monitor-only mode (counted and alerted, not enforced).</p>}
      {low && <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> Credit is running low — top up the provider account.</p>}
    </div>
  );
}
const Stat = ({ label, value, color }) => (
  <div><small style={{ opacity: 0.6 }}>{label}</small><div style={{ fontWeight: 700, color }}>{value}</div></div>
);

/** Superadmin: freeze time, target risk, Turnstile, contact-change quotas, break-glass. SMS settings live in the SMS tab. */
export default function SecurityPanel() {
  const toast = useToast();
  const confirm = useConfirm();
  const [d, setD] = useState(null);
  const [f, setF] = useState({});
  // One reason box per form: they used to share a single value, so text typed for one save appeared in the others.
  const [reasonSec, setReasonSec] = useState('');
  const [ledger, setLedger] = useState(null);
  const [tz, setTz] = useState(DEFAULT_TZ);   // election timezone (set on the Timeline tab)
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      // One parallel round-trip. SMS settings, budget and usage now live in the SMS tab (SmsPanel).
      const [rr, sched] = await Promise.all([
        api.get('/superadmin/security-settings'),
        api.get('/admin/schedule'),
      ]);
      const r = rr.data;
      const zone = sched.data.timezone || DEFAULT_TZ;
      setTz(zone);
      setD(r);
      setF({ ...r.settings, roster_freeze_at: utcToZonedInput(r.settings.roster_freeze_at, zone) });
    } catch (e) { setFailed(true); toast(errMsg(e, 'Could not load security settings.'), { kind: 'error' }); }
  }, [toast]);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);
  useRevealReady(Boolean(d) || failed);
  if (!d) return null;

  const need = (r) => { if (r.trim().length < 3) { toast('Enter a reason for this change first.', { kind: 'error' }); return false; } return true; };
  // A failed or timed-out save may still have been applied on the server, so always re-read the real values.
  const saveFailed = (e) => {
    toast(e?.response ? errMsg(e, 'Save failed.') : 'No answer from the server. The change may still have been applied; showing the current saved values.', { kind: 'error' });
    load();
  };
  const savedOk = (msg, r) => {
    const warn = r?.data?.warning;
    if (warn) toast(warn, { kind: 'info' }); else toast(msg, { kind: 'success' });
    load();
  };
  const saveSecurity = async () => {
    if (!need(reasonSec)) return;
    if (!(await confirm('Save these security settings? The change is logged with your reason and shown to the overseer.', { confirmText: 'Save' }))) return;
    const body = { reason: reasonSec.trim() };
    ['roster_freeze_enabled', 'contact_change_required', 'superadmin_breakglass'].forEach(k => { body[k] = Boolean(f[k]); });
    ['otp_target_risk', 'quota_alert_pct', 'quota_hard_cap_pct'].forEach(k => { body[k] = Number(f[k]); });
    ['contact_change_ttl_hours', 'contact_change_max_per_voter', 'approver_daily_cap',
      'reset_admin_hourly_alert', 'reset_admin_hourly_hard_cap', 'reset_per_voter_daily', 'reset_per_voter_election'].forEach(k => { body[k] = Number(f[k]); });
    body.turnstile_mode = f.turnstile_mode;
    body.public_results_mode = f.public_results_mode;
    body.unopposed_rule = f.unopposed_rule;
    ['unopposed_min_votes', 'unopposed_pct_voted', 'unopposed_pct_registered'].forEach(k => { body[k] = Number(f[k]); });
    body.approval_policy = f.approval_policy;
    if (f.roster_freeze_at) body.roster_freeze_at = zonedInputToUtcISO(f.roster_freeze_at, tz);
    else body.clear_roster_freeze_at = true;
    try { const r = await api.put('/superadmin/security-settings', body); setReasonSec(''); savedOk('Security settings saved.', r); }
    catch (e) { saveFailed(e); }
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
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))', gap: 16, alignItems: 'start' }}>
      <LegacyDataPanel />
      {d.banner && <div style={{ ...box, borderColor: 'var(--warning)', gridColumn: '1 / -1' }}><Icon name="warning" /> {d.banner} Schedule the voting phase (Timeline tab) with “enforced” on.</div>}

      <div style={box}>
        <b style={{ fontSize: 14 }}>Lock strength (derived from the voting window)</b>
        <p style={note}>
          Each voter gets {dv.free_guesses} free wrong guesses, then one more every <b>{Math.round(dv.refill_interval_seconds / 60)} min</b>
          {' '}(total budget ≈ {dv.guess_budget} guesses over the window). Changing the window recomputes this automatically.
        </p>
        <div style={grid}>{num('otp_target_risk', 'Target risk ε (per voter)', 0.00001)}</div>
      </div>

      <div style={{ ...box, gridColumn: '1 / -1' }}>
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
        <b style={{ fontSize: 14 }}>Candidate approval policy</b>
        <p style={note}>How the Vetting Panel's votes on candidate applications resolve. Changing this immediately re-checks every pending application against the new rule — it can flip an outcome without a new vote being cast.</p>
        <select style={inp} value={f.approval_policy} onChange={e => setF({ ...f, approval_policy: e.target.value })}>
          <option value="majority_total">Majority of total panel size (original behaviour)</option>
          <option value="unanimous">Unanimous — every panelist must agree</option>
          <option value="majority_cast">Majority of votes cast — resolves once everyone has voted</option>
        </select>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Public results visibility</b>
        <p style={note}>Controls when the public, unauthenticated results page shows numbers. This is per-org — it does not affect other organisations on this deployment.</p>
        <select style={inp} value={f.public_results_mode} onChange={e => setF({ ...f, public_results_mode: e.target.value })}>
          <option value="live">Live (visible while voting is open — original behaviour)</option>
          <option value="closed">Hidden until voting closes</option>
          <option value="certified">Hidden until a commissioner certifies results (recommended)</option>
        </select>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Unopposed candidates: minimum to be elected</b>
        <select style={inp} value={f.unopposed_rule || 'votes'} onChange={e => setF({ ...f, unopposed_rule: e.target.value })}>
          <option value="votes">A fixed number of votes</option>
          <option value="pct_voted">A percentage of the voters who voted</option>
          <option value="pct_registered">A percentage of registered voters</option>
        </select>
        <div style={grid}>
          {(f.unopposed_rule || 'votes') === 'votes' && num('unopposed_min_votes', 'Valid votes needed')}
          {f.unopposed_rule === 'pct_voted' && num('unopposed_pct_voted', '% of voters who voted', 0.5)}
          {f.unopposed_rule === 'pct_registered' && num('unopposed_pct_registered', '% of registered voters', 0.5)}
        </div>
        <p style={note}>A candidate running alone is declared elected (&ldquo;Mandate gained&rdquo;) only when their votes reach this minimum; otherwise the result shows &ldquo;Undermandated&rdquo;. Percentages are worked out from the live turnout or roster size and rounded up to a whole vote. It applies to the public results page and to the printed and signed reports, and cannot be changed once results are certified. Every change is logged with your reason.</p>
      </div>

      <div style={box}>
        <b style={{ fontSize: 14 }}>Bot check (Cloudflare Turnstile)</b>
        <select style={inp} value={f.turnstile_mode} onChange={e => setF({ ...f, turnstile_mode: e.target.value })}>
          <option value="off">Off</option><option value="adaptive">Adaptive (suspicious IPs / under attack)</option><option value="on">On (recommended for election day)</option>
        </select>
        {!dv.turnstile_secret_configured && f.turnstile_mode !== 'off' && <p style={{ ...note, color: 'var(--warning)' }}><Icon name="warning" /> TURNSTILE_SECRET is not set on the server, so the check cannot be enforced.</p>}
        {f.turnstile_mode !== 'off' && !turnstileConfigured && <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> VITE_TURNSTILE_SITE_KEY is not set in this frontend build, so voters cannot see the check. Keep this Off until it is set and the site is redeployed.</p>}
      </div>

      <CaptchaHealthTile />

      <label style={fld}><span style={lbl}>Reason for this change (required, logged)</span>
        <input style={inp} value={reasonSec} onChange={e => setReasonSec(e.target.value)} placeholder="e.g. election-day hardening" /></label>
      <button  onClick={saveSecurity} className="perf-btn perf-btn-primary">Save security settings</button>

      <NameNormalizerTile />

      <RegNumberCheckTile />
      <ApplicationEditReconcileTile />

      <div style={box}>
        <b style={{ fontSize: 14 }}>Roster ledger integrity</b>
        <button  onClick={verifyLedger} className="perf-btn" style={{ cursor: 'pointer', marginLeft: 10 }}>Verify chain</button>
        {ledger && <p style={{ ...note, color: ledger.valid ? 'var(--success)' : 'var(--danger)' }}>
          {ledger.valid ? `VERIFIED — ${ledger.entries} entries` : `MISMATCH at entry #${ledger.first_bad_seq}`}</p>}
      </div>
    </div>
  );
}

/** Superadmin maintenance: title-case every stored person name in the active organization. */
function NameNormalizerTile() {
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);

  const run = async (dryRun) => {
    if (!dryRun) {
      const ok = await confirm(
        'Rewrite the capitalisation of every name in the voter register, applications, candidates and change requests for this organisation? Only letter case and spacing change (e.g. "john OKELLO" becomes "John Okello"). Preview first if you have not already.',
        { confirmText: 'Apply to all names' });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const r = (await api.post('/superadmin/maintenance/normalize-names', { dry_run: dryRun })).data;
      setReport(r);
      if (r.dry_run) toast(r.total_changed ? `${r.total_changed} name(s) would change.` : 'All names are already in the right format.');
      else toast(`Updated ${r.total_changed} name(s).`, { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Name clean-up failed.'), { kind: 'error' }); }
    finally { setBusy(false); }
  };

  return (
    <div style={box}>
      <b style={{ fontSize: 14 }}>Name formatting clean-up</b>
      <p style={note}>New names are capitalised automatically when saved. This fixes names that were stored before that (voter register, applications, candidates, change requests). It changes letter case and spacing only. IDs, phone numbers, votes and the audit history are not touched.</p>
      <button  disabled={busy} onClick={() => run(true)} className="perf-btn" style={{ cursor: 'pointer' }}>Preview changes</button>
      <button  disabled={busy || !report || !report.dry_run || report.total_changed === 0} onClick={() => run(false)} className="perf-btn perf-btn-primary" style={{ cursor: 'pointer', marginLeft: 10 }}>Apply</button>
      {report && (
        <div style={{ marginTop: 10, fontSize: 13 }}>
          <div style={{ fontWeight: 700, color: report.dry_run ? 'inherit' : 'var(--success)' }}>
            {report.dry_run ? `Preview: ${report.total_changed} name(s) would change` : `Done: ${report.total_changed} name(s) updated`}
          </div>
          <div style={note}>{Object.entries(report.collections).map(([k, v]) => `${k}: ${v.changed}/${v.scanned}`).join('  ·  ')}</div>
          {report.samples.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
              {report.samples.map((x, i) => <li key={i}>{x.old} &rarr; <b>{x.new}</b></li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Superadmin maintenance: find registration numbers stored in a form the app cannot look up. */
function RegNumberCheckTile() {
  const idText = useIdText();
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState(null);

  const run = async (fix) => {
    if (fix) {
      const ok = await confirm(
        `Rewrite the affected ${idText.noun}s to the standard stored form (lowercase, no spaces)? Students shown as conflicts, and students who have already voted, are NOT touched. They are listed for manual review.`,
        { confirmText: `Fix ${idText.noun}s` });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const res = (await api.post('/superadmin/maintenance/check-reg-numbers', { fix })).data;
      setR(res);
      if (fix) toast(`Fixed ${res.total_fixed} record(s).`, { kind: 'success' });
      else toast(res.issues_found ? `${res.issues_found} record(s) need attention.` : `All ${idText.noun}s are in the correct form.`);
    } catch (e) { toast(errMsg(e, `${idText.nounCap} check failed.`), { kind: 'error' }); }
    finally { setBusy(false); }
  };

  const fixable = r ? r.voters.fixable + Object.values(r.other).reduce((n, c) => n + c.non_canonical, 0) : 0;
  return (
    <div style={box}>
      <b style={{ fontSize: 14 }}>{idText.nounCap} check</b>
      <p style={note}>{idText.nounCap}s are shown in capitals, but stored in one standard form (lowercase, no spaces) so that login and search can find them. This checks the database for any that are stored differently. Those students are on the register but cannot be found. Audit history is never rewritten.</p>
      <button  disabled={busy} onClick={() => run(false)} className="perf-btn" style={{ cursor: 'pointer' }}>Check database</button>
      <button  disabled={busy || !r || r.fix || fixable === 0} onClick={() => run(true)} className="perf-btn perf-btn-primary" style={{ cursor: 'pointer', marginLeft: 10 }}>Fix</button>
      {r && (
        <div style={{ marginTop: 10, fontSize: 13 }}>
          <div style={{ fontWeight: 700, color: r.issues_found === 0 || r.fix ? 'var(--success)' : 'var(--danger)' }}>
            {r.fix ? `Fixed ${r.total_fixed} record(s)` : r.issues_found === 0 ? 'No problems found' : `${r.issues_found} record(s) stored incorrectly`}
            {r.needs_review > 0 && ` · ${r.needs_review} need manual review`}
          </div>
          <div style={note}>
            Voters: {r.voters.scanned} checked, {r.voters.non_canonical} wrong, {r.voters.conflicts} conflicts, {r.voters.voted_review} already voted.
            {Object.entries(r.other).map(([k, c]) => `  ·  ${k}: ${c.non_canonical}/${c.scanned}`).join('')}
          </div>
          {r.samples.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
              {r.samples.map((x, i) => <li key={i}>[{x.kind.replace('_', ' ')}] {x.collection}: {x.old} &rarr; <b>{x.new}</b></li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Superadmin maintenance: record application edits made before edit tracking existed. */
function ApplicationEditReconcileTile() {
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);

  const run = async (dryRun) => {
    if (!dryRun) {
      const ok = await confirm(
        'Mark these applications as EDITED? Each gets one history entry recording the change, so the EDITED label and the extra PDF pages appear. Application details are not changed.',
        { confirmText: 'Record edits' });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const r = (await api.post('/superadmin/maintenance/reconcile-application-edits', { dry_run: dryRun })).data;
      setReport(r);
      if (r.dry_run) toast(r.items.length ? `${r.items.length} application(s) have unrecorded edits.` : 'No unrecorded edits found.');
      else toast(`Recorded edits on ${r.recorded} application(s).`, { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Edit check failed.'), { kind: 'error' }); }
    finally { setBusy(false); }
  };

  return (
    <div style={box}>
      <b style={{ fontSize: 14 }}>Unrecorded application edits</b>
      <p style={note}>Finds applications whose details were changed before the Edit application button existed, so they never showed as edited. Preview lists them; Apply records each change in its history. The edit time shown will be today, because the real time was never saved.</p>
      <button  disabled={busy} onClick={() => run(true)} className="perf-btn" style={{ cursor: 'pointer' }}>Preview</button>
      <button  disabled={busy || !report || !report.dry_run || report.items.length === 0} onClick={() => run(false)} className="perf-btn perf-btn-primary" style={{ cursor: 'pointer', marginLeft: 10 }}>Apply</button>
      {report && (
        <div style={{ marginTop: 10, fontSize: 13 }}>
          <div style={{ fontWeight: 700, color: report.dry_run ? 'inherit' : 'var(--success)' }}>
            {report.dry_run ? `Preview: ${report.items.length} of ${report.scanned} application(s) have unrecorded edits` : `Done: ${report.recorded} recorded`}
          </div>
          {report.items.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
              {report.items.map((x) => <li key={x.app_id}>{x.name}: <b>{x.fields.join(', ')}</b></li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Superadmin diagnostics for the bot check: config, Cloudflare reachability, live widget test, per-IP counters. */
function CaptchaHealthTile() {
  const toast = useToast();
  const [st, setSt] = useState(null);
  const [ping, setPing] = useState(null);
  const [busy, setBusy] = useState('');
  const [showWidget, setShowWidget] = useState(false);
  const [tok, setTok] = useState('');
  const [wKey, setWKey] = useState(0);
  const [wStatus, setWStatus] = useState('');
  const [vres, setVres] = useState(null);
  const [pubIp, setPubIp] = useState('');       // this browser's real public IP, from an outside lookup
  const [pubIpErr, setPubIpErr] = useState('');

  const loadStatus = useCallback(async () => {
    try { setSt((await api.get('/superadmin/captcha/status')).data); }
    catch (e) { toast(errMsg(e, 'Could not load bot check status.'), { kind: 'error' }); }
  }, [toast]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  const runPing = async () => {
    setBusy('ping');
    try { setPing((await api.post('/superadmin/captcha/ping')).data); }
    catch (e) { toast(errMsg(e, 'Reachability test failed.'), { kind: 'error' }); }
    finally { setBusy(''); }
  };
  const verify = async () => {
    setBusy('verify');
    try { setVres((await api.post('/superadmin/captcha/verify-token', { token: tok })).data); }
    catch (e) { toast(errMsg(e, 'Verification request failed.'), { kind: 'error' }); }
    finally { setBusy(''); setTok(''); setWKey(k => k + 1); }   // tokens are single-use
  };
  const detectPublicIp = async () => {
    setBusy('pubip'); setPubIpErr('');
    try {
      const r = await fetch('https://api.ipify.org?format=json', { cache: 'no-store' });
      setPubIp(String((await r.json()).ip || '').trim());
    } catch { setPubIpErr('Could not look up your public IP (blocked or offline). Type it in from any "what is my IP" site instead.'); }
    finally { setBusy(''); }
  };
  const clearIp = async () => {
    setBusy('ip');
    try {
      await api.delete('/superadmin/captcha/ip-stats', { data: { reason: 'superadmin captcha test' } });
      toast('Counters for your IP were cleared.', { kind: 'success' });
      await loadStatus();
    } catch (e) { toast(errMsg(e, 'Could not clear counters.'), { kind: 'error' }); }
    finally { setBusy(''); }
  };

  const c = st?.your_ip?.counts_30m;
  const ok = (v) => <b style={{ color: v ? 'var(--success)' : 'var(--danger)' }}>{v ? 'Yes' : 'No'}</b>;
  return (
    <div style={box}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <b style={{ fontSize: 14 }}>Bot check health</b>
        <button onClick={loadStatus} className="perf-btn" style={{ cursor: 'pointer' }}>Refresh</button>
      </div>
      {!st ? <p style={note}>Loading…</p> : (
        <>
          <div style={grid}>
            <Stat label="Mode" value={st.mode} />
            <Stat label="Server secret set" value={ok(st.secret_configured)} />
            <Stat label="Site key in this build" value={ok(turnstileConfigured)} />
            <Stat label="Cloudflare test keys" value={st.secret_is_cloudflare_test_key ? 'Yes (not real protection)' : 'No'} color={st.secret_is_cloudflare_test_key ? 'var(--warning)' : undefined} />
          </div>
          {st.secret_is_cloudflare_test_key && <p style={{ ...note, color: 'var(--warning)' }}><Icon name="warning" /> The secret looks like a Cloudflare dummy key. Replace it with the real secret before election day.</p>}

          <b style={{ fontSize: 13, display: 'block', marginTop: 12 }}>Proxy hops: which address does the server treat as the voter?</b>
          <p style={note}>Path: voter's phone → {st.proxy.forwarded_for.length > 1 ? 'Vercel → ' : ''}Render (this server). The server reads the client address from the <code>X-Forwarded-For</code> header, counting <code>TRUSTED_PROXY_HOPS</code> entries from the right. Currently set to <b>{st.proxy.trusted_hops}</b>, which picks <code>{st.your_ip.detected}</code>.</p>
          <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ textAlign: 'left', opacity: 0.65 }}><th style={cell}>TRUSTED_PROXY_HOPS</th><th style={cell}>Address the server would use</th><th style={cell}>Matches your public IP</th></tr></thead>
            <tbody>
              {st.proxy.candidates.map(cd => {
                const match = pubIp && cd.ip === pubIp;
                const current = cd.hops === st.proxy.trusted_hops;
                return (
                  <tr key={cd.hops} style={{ background: current ? 'var(--card-bg)' : 'transparent', fontWeight: current ? 700 : 400 }}>
                    <td style={cell}>{cd.hops}{current ? ' (current)' : ''}</td>
                    <td style={cell}><code>{cd.ip || '—'}</code></td>
                    <td style={cell}>{!pubIp ? '—' : match ? <span style={{ color: 'var(--success)' }}>Yes</span> : 'No'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
            <button disabled={busy === 'pubip'} onClick={detectPublicIp} className="perf-btn" style={{ cursor: 'pointer' }}>{busy === 'pubip' ? 'Looking up…' : 'Detect my public IP'}</button>
            <input style={{ ...inp, width: 220 }} value={pubIp} onChange={e => setPubIp(e.target.value.trim())} placeholder="or type your public IP" />
          </div>
          {pubIpErr && <p style={{ ...note, color: 'var(--warning)' }}>{pubIpErr}</p>}
          {(() => {
            const hit = pubIp ? st.proxy.candidates.find(cd => cd.ip === pubIp) : null;
            if (!pubIp) return <p style={note}>Click <b>Detect my public IP</b> (uses api.ipify.org from your browser) so the panel can tell you the right value. Do this from the same network and the same site address voters use.</p>;
            if (!hit) return <p style={{ ...note, color: 'var(--warning)' }}><Icon name="warning" /> None of the options gives <code>{pubIp}</code>. If your connection uses IPv6, a VPN or a different network path than the one this page just used, try another network and refresh. Do not change the setting until one row matches.</p>;
            if (hit.hops === st.proxy.trusted_hops) return <p style={{ ...note, color: 'var(--success)' }}>Correct: <code>TRUSTED_PROXY_HOPS={hit.hops}</code> already gives the real voter IP.</p>;
            return <p style={{ ...note, color: 'var(--danger)' }}><Icon name="warning" /> Set <code>TRUSTED_PROXY_HOPS={hit.hops}</code> on the backend (Render → Environment), redeploy, then click Refresh. Until then every voter is counted as <code>{st.your_ip.detected}</code>.</p>;
          })()}
          <p style={note}>Why it matters: if all voters share one address, adaptive mode challenges everyone and the per-IP limits are shared across the whole election.</p>

          <div style={grid}>
            <Stat label="Sends (30 min)" value={`${c.sends} / ${st.thresholds.min_sends}`} />
            <Stat label="Verifies (30 min)" value={c.verifies} />
            <Stat label="Failures (30 min)" value={`${c.fails} / ${st.thresholds.max_fails}`} />
            <Stat label="Flagged for challenge" value={c.flagged ? 'Yes' : 'No'} color={c.flagged ? 'var(--warning)' : undefined} />
          </div>
          <p style={note}>An IP is challenged in adaptive mode at {st.thresholds.min_sends}+ sends with under {Math.round(st.thresholds.max_verify_ratio * 100)}% verified, or {st.thresholds.max_fails}+ failures, within {st.thresholds.window_minutes} minutes.</p>
          <button disabled={busy === 'ip'} onClick={clearIp} className="perf-btn" style={{ cursor: 'pointer' }}>Clear counters for my IP</button>

          <hr style={{ border: 0, borderTop: '1px solid var(--border-color)', margin: '14px 0' }} />
          <b style={{ fontSize: 13 }}>Cloudflare connection</b>
          <p style={note}>Sends a dummy token from the server to confirm Cloudflare is reachable and the secret is accepted. No SMS is sent.</p>
          <button disabled={busy === 'ping'} onClick={runPing} className="perf-btn perf-btn-primary" style={{ cursor: 'pointer' }}>{busy === 'ping' ? 'Testing…' : 'Test connection'}</button>
          {ping && (
            <p style={{ ...note, opacity: 1 }}>
              {!ping.configured ? <span style={{ color: 'var(--warning)' }}>{ping.detail}</span>
                : !ping.reachable ? <span style={{ color: 'var(--danger)' }}>Cloudflare is unreachable from the server{ping.error ? ` (${ping.error})` : ''}.</span>
                : ping.secret_valid ? <span style={{ color: 'var(--success)' }}>Reachable ({ping.latency_ms} ms) and the secret is accepted.</span>
                : <span style={{ color: 'var(--danger)' }}>Reachable ({ping.latency_ms} ms) but Cloudflare rejected the secret: {ping.error_codes.join(', ') || 'unknown'}.</span>}
            </p>
          )}

          <hr style={{ border: 0, borderTop: '1px solid var(--border-color)', margin: '14px 0' }} />
          <b style={{ fontSize: 13 }}>Live widget test</b>
          <p style={note}>Loads the real widget in this browser, then verifies its token on the server. Use it from a phone on mobile data to see what voters will see.</p>
          {!turnstileConfigured ? <p style={{ ...note, color: 'var(--danger)' }}>No site key in this build, so there is nothing to test.</p>
            : !showWidget ? <button onClick={() => setShowWidget(true)} className="perf-btn" style={{ cursor: 'pointer' }}>Load widget</button>
            : (
              <>
                <TurnstileWidget onToken={setTok} resetKey={wKey} onStatus={setWStatus} />
                <p style={note}>Widget: <b>{wStatus === 'ready' ? 'token received' : wStatus === 'failed' ? 'failed to load' : 'loading…'}</b></p>
                <button disabled={!tok || busy === 'verify'} onClick={verify} className="perf-btn perf-btn-primary" style={{ cursor: 'pointer' }}>Verify token on server</button>
              </>
            )}
          {vres && (
            <p style={{ ...note, opacity: 1 }}>
              {vres.passed ? <span style={{ color: 'var(--success)' }}>Passed{vres.hostname ? ` for ${vres.hostname}` : ''} ({vres.latency_ms} ms).</span>
                : <span style={{ color: 'var(--danger)' }}>Failed: {vres.error_codes.join(', ') || vres.error || 'unknown reason'}.</span>}
            </p>
          )}
        </>
      )}
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--bg-color)' };
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginTop: 10 };
const cell = { padding: '6px 8px', borderBottom: '1px solid var(--border-color)' };
const note = { fontSize: 12, opacity: 0.75, margin: '6px 0' };
const fld = { display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 };
const lbl = { fontSize: 12, opacity: 0.65, fontWeight: 600 };
const inp = { padding: '9px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, width: '100%', boxSizing: 'border-box' };

