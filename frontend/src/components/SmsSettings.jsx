import React, { useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm } from './UIFeedback';
import { Icon } from './icons.jsx';
import { errMsg } from '../studentEdit';

// SMS settings cards (moved here from SecurityPanel): routing, test and check, budget, and the new pricing and
// message-length card. Kit classes only (docs/UI_TEMPLATE_MANUAL.md). Every save needs a reason and is logged.

export const ROUTE_LABELS = {
  default: 'Automatic (original behaviour)',
  egosms_first: 'EgoSMS first, MamboSMS as fallback',
  mambosms_first: 'MamboSMS first, EgoSMS as fallback',
  egosms_only: 'EgoSMS only (no fallback)',
  mambosms_only: 'MamboSMS only (no fallback)',
};
/** What "Automatic" actually does, so nobody has to guess. */
const AUTO_ORDER = { otp: 'EgoSMS, then MamboSMS if it fails', other: 'MamboSMS, then EgoSMS if it fails' };
const PROVIDERS = [['egosms', 'EgoSMS'], ['mambosms', 'MamboSMS']];
const LIMIT_FIELDS = [
  ['single_limit', 'Characters in a one-part SMS'],
  ['multi_limit', 'Characters per part (multi-part)'],
  ['unicode_single_limit', 'One-part limit with non-GSM characters'],
  ['unicode_multi_limit', 'Per-part limit with non-GSM characters'],
];
const fieldBox = { display: 'grid', gap: 4, marginTop: 10 };
const lblStyle = { fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' };

const Reason = ({ value, onChange, placeholder }) => (
  <label style={fieldBox}><span style={lblStyle}>Reason for this change (required, logged)</span>
    <input className="perf-field" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} /></label>
);

function useSaver(onSaved) {
  const toast = useToast();
  const needReason = (r) => { if (r.trim().length < 3) { toast('Enter a reason for this change first.', { kind: 'error' }); return false; } return true; };
  // A failed or timed-out save may still have been applied on the server, so always re-read the real values.
  const failed = (e) => {
    toast(e?.response ? errMsg(e, 'Save failed.') : 'No answer from the server. The change may still have been applied; showing the current saved values.', { kind: 'error' });
    onSaved();
  };
  const ok = (msg) => { toast(msg, { kind: 'success' }); onSaved(); };
  return { toast, needReason, failed, ok };
}

/** Which provider carries each kind of message. */
export function SmsRoutingSettings({ settings, derived, onSaved }) {
  const confirm = useConfirm();
  const { needReason, failed, ok } = useSaver(onSaved);
  const [f, setF] = useState({ otp: 'default', other: 'default', fallback: false });
  const [reason, setReason] = useState('');
  useEffect(() => {
    setF({ otp: settings.sms_route_otp || 'default', other: settings.sms_route_other || 'default', fallback: Boolean(settings.sms_fallback_on_timeout) });
  }, [settings.sms_route_otp, settings.sms_route_other, settings.sms_fallback_on_timeout]);
  const routes = derived.sms_routes || Object.keys(ROUTE_LABELS);
  const conf = derived.sms_providers_configured;
  const save = async () => {
    if (!needReason(reason)) return;
    const warn = [f.otp, f.other].some((r) => r === 'egosms_only' || r === 'mambosms_only');
    const msg = warn
      ? 'Save SMS routing? A provider set to "only" has NO fallback: if that provider is down or out of credit, those messages will not be delivered. Send a test first.'
      : 'Save SMS routing? It takes effect immediately for every new message.';
    if (!(await confirm(msg, { confirmText: 'Save routing' }))) return;
    try {
      await api.put('/superadmin/security-settings', {
        reason: reason.trim(), sms_route_otp: f.otp, sms_route_other: f.other, sms_fallback_on_timeout: f.fallback,
      });
      setReason(''); ok('SMS routing saved.');
    } catch (e) { failed(e); }
  };
  return (
    <section className="perf-card card-pad">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>SMS delivery &amp; routing</h3>
      <p className="perf-lead">Choose which provider carries each kind of message. Bulk messages follow “Everything else”. Changes apply immediately to new messages.</p>
      <label style={fieldBox}><span style={lblStyle}>Voter OTP codes</span>
        <select className="perf-field" value={f.otp} onChange={(e) => setF({ ...f, otp: e.target.value })}>
          {routes.map((r) => <option key={r} value={r}>{ROUTE_LABELS[r] || r}</option>)}
        </select></label>
      <label style={fieldBox}><span style={lblStyle}>Everything else (bulk SMS, admin passwords, notices, candidate links)</span>
        <select className="perf-field" value={f.other} onChange={(e) => setF({ ...f, other: e.target.value })}>
          {routes.map((r) => <option key={r} value={r}>{ROUTE_LABELS[r] || r}</option>)}
        </select></label>
      <p className="perf-note">“Automatic” means: OTP codes → {AUTO_ORDER.otp}; everything else → {AUTO_ORDER.other}.</p>
      {conf && PROVIDERS.filter(([p]) => !conf[p]).map(([p, label]) => (
        <p key={p} className="perf-msg" data-kind="error"><Icon name="warning" /> {label} credentials are not set on the server, so this provider cannot send.</p>
      ))}
      {conf && [['egosms_only', 'egosms', 'EgoSMS'], ['mambosms_only', 'mambosms', 'MamboSMS']].map(([route, p, label]) => (
        [f.otp, f.other].includes(route) && !conf[p]
          ? <p key={route} className="perf-msg" data-kind="error"><Icon name="warning" /> A route is set to {label} only but {label} is not configured. Those messages will fail.</p> : null
      ))}
      <div className="perf-checks">
        <label className="perf-check"><input type="checkbox" checked={f.fallback} onChange={(e) => setF({ ...f, fallback: e.target.checked })} />
          <span>Also switch provider when the first one times out (result unknown). Risk: a student may receive a message twice.</span></label>
      </div>
      <Reason value={reason} onChange={setReason} placeholder="e.g. EgoSMS credit low, routing notices via MamboSMS" />
      <div className="perf-btnbar" style={{ marginTop: 10 }}>
        <button type="button" className="perf-btn perf-btn-primary" onClick={save}>Save SMS routing</button>
      </div>
    </section>
  );
}

/** Real (billable) test sends and the live provider balances. */
export function SmsTestSettings({ balances, onBalances }) {
  const { toast } = useSaver(() => {});
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState('');
  const send = async (provider) => {
    if (!phone.trim()) { toast('Enter a phone number to send the test to.', { kind: 'error' }); return; }
    setBusy(provider || 'routing');
    try {
      const r = (await api.post('/admin/test-connection', { phone: phone.trim(), ...(provider ? { provider } : {}) })).data;
      toast(r.message || 'Test sent.', { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Test failed.'), { kind: 'error' }); } finally { setBusy(''); }
  };
  const check = async () => {
    setBusy('balances');
    try { onBalances((await api.get('/admin/sms-balance')).data); }
    catch (e) { toast(errMsg(e, 'Could not read provider balances.'), { kind: 'error' }); } finally { setBusy(''); }
  };
  return (
    <section className="perf-card card-pad">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>Test &amp; check providers</h3>
      <p className="perf-lead">Sends a real (billable) test message. “Current routing” behaves like a notice; the provider buttons test one account directly, ignoring routing.</p>
      <input className="perf-field" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Phone, e.g. 2567XXXXXXXX" aria-label="Phone number for the test" />
      <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 10 }}>
        <button type="button" className="perf-btn" disabled={!!busy} onClick={() => send()}>{busy === 'routing' ? 'Sending…' : 'Current routing'}</button>
        <button type="button" className="perf-btn" disabled={!!busy} onClick={() => send('egosms')}>{busy === 'egosms' ? 'Sending…' : 'EgoSMS'}</button>
        <button type="button" className="perf-btn" disabled={!!busy} onClick={() => send('mambosms')}>{busy === 'mambosms' ? 'Sending…' : 'MamboSMS'}</button>
        <button type="button" className="perf-btn" disabled={!!busy} onClick={check}>{busy === 'balances' ? 'Checking…' : 'Check balances'}</button>
      </div>
      {balances && (
        <p className="perf-note">
          EgoSMS: <b>{balances.egosms?.balance ?? '—'}</b>{balances.egosms?.error ? ` (${balances.egosms.error})` : ''} · MamboSMS: <b>{balances.mambosms?.balance ?? '—'}</b>{balances.mambosms?.error ? ` (${balances.mambosms.error})` : ''}
        </p>
      )}
    </section>
  );
}

/** SMS budget (count of messages), mode, live balance floor. */
export function SmsBudgetSettings({ usage, derived, onSaved }) {
  const { needReason, failed, ok } = useSaver(onSaved);
  const [b, setB] = useState({ total: '', mode: 'normal', enforce: false, floor: '' });
  const [reason, setReason] = useState('');
  useEffect(() => {
    setB({ total: usage.budget_total ?? '', mode: usage.mode === 'conservation' ? 'conservation' : 'normal', enforce: Boolean(usage.budget_enforced), floor: usage.balance_floor_ugx ?? '' });
  }, [usage.budget_total, usage.mode, usage.budget_enforced, usage.balance_floor_ugx]);
  const save = async () => {
    if (!needReason(reason)) return;
    try {
      await api.put('/superadmin/sms-budget', {
        reason: reason.trim(), sms_budget_total: b.total === '' ? undefined : Number(b.total),
        sms_mode: b.mode, sms_budget_enforce: b.enforce, sms_balance_floor_ugx: b.floor === '' ? 0 : Number(b.floor),
      });
      setReason(''); ok('SMS budget saved.');
    } catch (e) { failed(e); }
  };
  return (
    <section className="perf-card card-pad">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>SMS budget</h3>
      <p className="perf-lead">Suggested: <b>{derived.suggested_sms_budget}</b> (voters × 2.5). Raising the budget re-arms the 50/25/10% alerts. Bulk messages count one per part.</p>
      <label style={fieldBox}><span style={lblStyle}>Budget (SMS)</span>
        <input className="perf-field" type="number" value={b.total} onChange={(e) => setB({ ...b, total: e.target.value })} /></label>
      <label style={fieldBox}><span style={lblStyle}>Mode</span>
        <select className="perf-field" value={b.mode} onChange={(e) => setB({ ...b, mode: e.target.value })}>
          <option value="normal">Normal</option>
          <option value="conservation">Conservation (last resort: first codes only; bulk sending is blocked)</option>
        </select></label>
      <label style={fieldBox}><span style={lblStyle}>Live balance floor (UGX, blank = off)</span>
        <input className="perf-field" type="number" value={b.floor} onChange={(e) => setB({ ...b, floor: e.target.value })} /></label>
      <p className="perf-note">If set, periodically checks the EgoSMS + MamboSMS live balance and alerts if it drops below this.</p>
      <div className="perf-checks">
        <label className="perf-check"><input type="checkbox" checked={b.enforce} onChange={(e) => setB({ ...b, enforce: e.target.checked })} />
          <span>Enforce (leave off / monitor-only until the dry run passes). When on, a bulk send larger than the remaining budget is refused.</span></label>
      </div>
      <Reason value={reason} onChange={setReason} placeholder="e.g. topped up 5,000 credits" />
      <div className="perf-btnbar" style={{ marginTop: 10 }}>
        <button type="button" className="perf-btn perf-btn-primary" onClick={save}>Save SMS budget</button>
      </div>
    </section>
  );
}

const toForm = (pricing) => Object.fromEntries(PROVIDERS.map(([p]) => [p, {
  cost_per_part_ugx: pricing?.[p]?.cost_per_part_ugx ?? '',
  ...Object.fromEntries(LIMIT_FIELDS.map(([k]) => [k, pricing?.[p]?.[k] ?? ''])),
}]));

/** Per-provider price per part and message-length limits, plus the bulk send rate. */
export function SmsPricingSettings({ usage, onSaved }) {
  const { needReason, failed, ok } = useSaver(onSaved);
  const [form, setForm] = useState(() => toForm(usage.sms_pricing));
  const [rate, setRate] = useState(usage.sms_bulk_per_second ?? 3);
  const [reason, setReason] = useState('');
  useEffect(() => { setForm(toForm(usage.sms_pricing)); setRate(usage.sms_bulk_per_second ?? 3); }, [usage.sms_pricing, usage.sms_bulk_per_second]);
  const set = (p, k, v) => setForm((f) => ({ ...f, [p]: { ...f[p], [k]: v } }));
  const save = async () => {
    if (!needReason(reason)) return;
    const body = {};
    for (const [p] of PROVIDERS) {
      const c = form[p].cost_per_part_ugx;
      body[p] = { cost_per_part_ugx: c === '' ? null : Number(c) };
      for (const [k] of LIMIT_FIELDS) body[p][k] = Number(form[p][k]);
    }
    try {
      await api.put('/superadmin/sms-budget', { reason: reason.trim(), sms_pricing: body, sms_bulk_per_second: Number(rate) });
      setReason(''); ok('SMS pricing saved.');
    } catch (e) { failed(e); }
  };
  return (
    <section className="perf-card card-pad">
      <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>SMS pricing &amp; message length</h3>
      <p className="perf-lead">Used by the calculator. Check with each provider whether it bills per part and what its real limits are. Leave a cost empty if unknown: totals then show “not set” rather than 0.</p>
      {PROVIDERS.map(([p, label]) => (
        <div key={p} className="perf-row" style={{ display: 'grid', gap: 8 }}>
          <span className="perf-row-title">{label}</span>
          <label style={fieldBox}><span style={lblStyle}>Cost per SMS part (UGX)</span>
            <input className="perf-field" type="number" min="0" step="any" value={form[p].cost_per_part_ugx} onChange={(e) => set(p, 'cost_per_part_ugx', e.target.value)} /></label>
          {LIMIT_FIELDS.map(([k, text]) => (
            <label key={k} style={fieldBox}><span style={lblStyle}>{text}</span>
              <input className="perf-field" type="number" min="1" max="1000" value={form[p][k]} onChange={(e) => set(p, k, e.target.value)} /></label>
          ))}
        </div>
      ))}
      <label style={fieldBox}><span style={lblStyle}>Bulk send rate (messages per second, 1 to 20)</span>
        <input className="perf-field" type="number" min="1" max="20" value={rate} onChange={(e) => setRate(e.target.value)} /></label>
      <Reason value={reason} onChange={setReason} placeholder="e.g. rates from the provider's price list, October" />
      <div className="perf-btnbar" style={{ marginTop: 10 }}>
        <button type="button" className="perf-btn perf-btn-primary" onClick={save}>Save pricing</button>
      </div>
    </section>
  );
}
