import React, { useCallback, useEffect, useRef, useState } from 'react';
import api from '../api';
import { startPolling } from '../hooks/usePolling';
import { useToast, useConfirm } from './UIFeedback';
import { LoadingBlock } from './Spinner.jsx';
import { SmsUsageTile } from './SecurityPanel';
import {
  SmsRoutingSettings, SmsTestSettings, SmsBudgetSettings, SmsPricingSettings,
} from './SmsSettings.jsx';
import { errMsg } from '../studentEdit';
import {
  countParts, unknownTokens, variableNames, insertAtCaret, breakdownLabel, ugx, costPerSms,
  systemTotals, balanceNumber, partsAffordable, normalizePct, splitLabel, shortfalls,
} from '../smsCalc';

// The SMS tab: compose to any audience, see the exact cost, send as a background campaign, and every SMS setting.
// Kit classes only, no template branches (docs/UI_TEMPLATE_MANUAL.md). The audience total is computed on the
// server (POST /admin/sms/audience); smsCalc.js only drives the instant preview of one message.

const PROVIDER_LABEL = { egosms: 'EgoSMS', mambosms: 'MamboSMS' };
const fieldBox = { display: 'grid', gap: 4, marginTop: 10 };
const lblStyle = { fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' };
const H3 = { margin: '0 0 6px', fontSize: 15 };
const TILE_VALUE = { fontSize: 20, lineHeight: 1.2, overflowWrap: 'anywhere' };
const ACTIVE = ['queued', 'running'];
const GROUP_ORDER = ['Voters', 'Applicants', 'Staff'];
const splitList = (t) => t.split(/[,\n;]+/).map((x) => x.trim()).filter(Boolean);

export default function SmsPanel() {
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState(null);          // { settings, derived, usage }
  const [loadFailed, setLoadFailed] = useState(false);
  const [balances, setBalances] = useState(null);
  const [fields, setFields] = useState([]);
  const [template, setTemplate] = useState('');
  const [voted, setVoted] = useState('any');
  const [attrText, setAttrText] = useState({});
  const [regText, setRegText] = useState('');
  const [plan, setPlan] = useState(null);          // last good audience result: kept visible while a new one loads
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState('');
  const [route, setRoute] = useState('default');   // bulk provider: default | egosms | mambosms | split
  const [egoPct, setEgoPct] = useState('50');       // EgoSMS share when splitting
  const [reason, setReason] = useState('');
  const [whatIf, setWhatIf] = useState('');       // optional: cost for a number of people typed by hand
  const [campaign, setCampaign] = useState(null);
  const [failedRows, setFailedRows] = useState(null);
  const [sending, setSending] = useState(false);
  const [sysTpl, setSysTpl] = useState(null);       // automatic system messages, priced (GET /admin/sms/templates)
  const [sysError, setSysError] = useState('');
  const [qty, setQty] = useState({});               // how many of each system message the person expects
  const taRef = useRef(null);
  const reqId = useRef(0);

  const load = useCallback(async () => {
    try {
      const [sec, usage] = await Promise.all([api.get('/superadmin/security-settings'), api.get('/superadmin/sms-budget')]);
      setData({ settings: sec.data.settings, derived: sec.data.derived, usage: usage.data });
      setLoadFailed(false);
    } catch (e) { setLoadFailed(true); toast(errMsg(e, 'Could not load the SMS settings.'), { kind: 'error' }); }
  }, [toast]);

  useEffect(() => {
    const t = setTimeout(load, 0);
    api.get('/admin/sms-balance').then((r) => setBalances(r.data)).catch(() => {});
    api.get('/admin/voter-fields').then((r) => setFields(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    api.get('/admin/sms/campaigns').then((r) => setCampaign(r.data.campaigns?.[0] || null)).catch(() => {});
    api.get('/admin/sms/templates').then((r) => setSysTpl(r.data.templates || [])).catch((e) => setSysError(errMsg(e, 'Could not load the system messages.')));
    return () => clearTimeout(t);
  }, [load]);

  // Poll the running campaign (every 2 s) until it finishes.
  const campaignId = campaign?.id;
  const campaignActive = campaign && ACTIVE.includes(campaign.status);
  useEffect(() => {
    if (!campaignId || !campaignActive) return undefined;
    const tick = () => api.get(`/admin/sms/campaigns/${campaignId}`).then((r) => setCampaign(r.data)).catch(() => {});
    return startPolling(tick, 2000, { minGapMs: 1500 });
  }, [campaignId, campaignActive]);

  const fieldKeys = fields.map((f) => f.key);
  const variables = variableNames(fieldKeys);
  const body = useCallback(() => ({
    template,
    voted,
    attrs: Object.fromEntries(Object.entries(attrText).map(([k, v]) => [k, splitList(v)]).filter(([, v]) => v.length)),
    reg_numbers: splitList(regText),
    route,
    ego_pct: normalizePct(egoPct),
  }), [template, voted, attrText, regText, route, egoPct]);

  // Debounced audience + cost (about 500 ms after the last change). The previous result stays on screen meanwhile.
  const ready = Boolean(data);
  useEffect(() => {
    if (!ready) return undefined;
    const id = ++reqId.current;
    setPlanBusy(true);
    const t = setTimeout(async () => {
      try {
        const r = await api.post('/admin/sms/audience', body());
        if (id !== reqId.current) return;
        setPlan(r.data); setPlanError('');
      } catch (e) {
        if (id === reqId.current) setPlanError(errMsg(e, 'Could not work out the audience.'));
      } finally { if (id === reqId.current) setPlanBusy(false); }
    }, 500);
    return () => clearTimeout(t);
  }, [ready, body]);

  if (!data) return loadFailed ? <section className="perf-card card-pad"><p className="perf-msg" data-kind="error">Could not load the SMS settings.</p></section> : <LoadingBlock text="Loading SMS…" />;
  const { settings, derived, usage } = data;

  const provider = plan?.provider || (route === 'split' ? 'split' : (PROVIDER_LABEL[route] ? route
    : (usage.sms_route_other === 'mambosms_only' ? 'mambosms' : 'egosms')));
  const isSplit = provider === 'split';
  const priceProvider = isSplit ? (plan?.provider_order?.[0] || 'mambosms') : provider;
  const rateLabel = isSplit ? splitLabel(plan?.ego_pct ?? normalizePct(egoPct)) : PROVIDER_LABEL[provider];
  const limits = usage.sms_pricing?.[priceProvider] || {};
  const local = countParts(template, limits);
  const tcount = plan?.template_count || local;
  const bad = unknownTokens(template, variables);
  const unit = plan ? plan.unit_cost : (limits.cost_per_part_ugx ?? null);
  // One provider: its price per SMS. Split: the average across both, since each message goes to one of them.
  const perSms = isSplit
    ? (plan && plan.total_cost != null && plan.recipients > 0 ? plan.total_cost / plan.recipients : null)
    : costPerSms(tcount.parts, unit);
  const short = plan ? shortfalls(plan.by_provider, balances) : [];
  const overBalance = short.length > 0;
  const whatIfN = whatIf === '' ? null : Math.max(0, Math.floor(Number(whatIf)) || 0);
  const whatIfCost = whatIfN == null || perSms == null ? null : perSms * whatIfN;
  const campaignRunning = Boolean(campaignActive);
  const canSend = Boolean(plan) && !planBusy && !planError && template.trim() && plan.recipients > 0 && plan.pricing_set
    && bad.length === 0 && reason.trim().length >= 3 && !campaignRunning && !sending;

  // Balances as boxes, and the system-message totals measured against them.
  const balText = (p) => {
    if (!balances) return '…';
    const n = balanceNumber(balances[p]?.balance);
    return balances[p]?.error || n == null ? '—' : `${n.toLocaleString('en-US')} ${balances[p].currency || ''}`.trim();
  };
  const budgetLow = usage.budget_pct_left != null && usage.budget_pct_left <= 25;
  const sys = systemTotals(sysTpl, qty);
  const sysGroups = GROUP_ORDER.map((g) => [g, (sysTpl || []).filter((t) => t.group === g)]).filter(([, items]) => items.length);
  const campaignIncluded = Boolean(plan) && template.trim().length > 0 && plan.recipients > 0;
  const campaignCost = campaignIncluded ? plan.total_cost : 0;
  const everything = sys.cost == null || campaignCost == null ? null : sys.cost + campaignCost;
  const needs = ['egosms', 'mambosms'].map((p) => {
    const s = sys.byProvider[p];
    const part = campaignIncluded ? plan.by_provider?.[p] : null;
    const camp = Boolean(part);
    const cost = (s?.cost || 0) + (camp ? (part.total_cost || 0) : 0);
    const unpriced = Boolean(s?.unpriced) || (camp && part.total_cost == null);
    return { p, cost, unpriced, used: Boolean(s?.parts) || camp };
  }).filter((n) => n.used);

  const insertVar = (name) => {
    const el = taRef.current;
    const r = insertAtCaret(template, `{${name}}`, el?.selectionStart, el?.selectionEnd);
    setTemplate(r.text);
    requestAnimationFrame(() => { if (el) { el.focus(); el.setSelectionRange(r.caret, r.caret); } });
  };

  const send = async () => {
    const msg = `Send this message to ${plan.recipients} student${plan.recipients === 1 ? '' : 's'}?\n\n`
      + `SMS parts: ${plan.total_parts}\nEstimated cost: ${ugx(plan.total_cost)} (${rateLabel} rates)\nSent via: ${isSplit ? rateLabel : PROVIDER_LABEL[plan.provider]}`
      + `${isSplit ? `\n${Object.entries(plan.by_provider).map(([p, b]) => `${PROVIDER_LABEL[p]}: ${b.recipients} SMS, ${b.total_parts} parts, ${ugx(b.total_cost)}`).join('\n')}` : ''}`
      + `${overBalance ? `\n\nWARNING: this is more than the ${short.map((p) => PROVIDER_LABEL[p]).join(' and ')} balance.` : ''}\n\nSending cannot be recalled and is billed.`;
    if (!(await confirm(msg, { confirmText: 'Send now' }))) return;
    setSending(true);
    try {
      const r = await api.post('/admin/sms/send', { ...body(), reason: reason.trim() });
      setCampaign(r.data); setFailedRows(null); setReason('');
      toast('Sending started.', { kind: 'success' });
    } catch (e) { toast(errMsg(e, 'Could not start sending.'), { kind: 'error' }); } finally { setSending(false); }
  };
  const cancel = async () => {
    if (!(await confirm('Stop this campaign? Messages already sent cannot be recalled.', { confirmText: 'Stop sending' }))) return;
    try { setCampaign((await api.post(`/admin/sms/campaigns/${campaign.id}/cancel`, { reason: 'Cancelled from the SMS tab' })).data); }
    catch (e) { toast(errMsg(e, 'Could not stop the campaign.'), { kind: 'error' }); }
  };
  const showFailed = async () => {
    try { setFailedRows((await api.get(`/admin/sms/campaigns/${campaign.id}`, { params: { failed: true } })).data.failed_recipients || []); }
    catch (e) { toast(errMsg(e, 'Could not load the failed list.'), { kind: 'error' }); }
  };
  const retry = async () => {
    if (!(await confirm(`Retry the ${campaign.failed} failed message(s)? Messages whose result is unknown are not retried.`, { confirmText: 'Retry failed' }))) return;
    try { setCampaign((await api.post(`/admin/sms/campaigns/${campaign.id}/retry-failed`, { reason: 'Retry failed from the SMS tab' })).data); setFailedRows(null); }
    catch (e) { toast(errMsg(e, 'Could not retry.'), { kind: 'error' }); }
  };

  const pct = campaign && campaign.recipients ? Math.round(100 * (campaign.sent + campaign.failed + campaign.ambiguous) / campaign.recipients) : 0;

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {/* 1. Balances and usage */}
      <section className="perf-card card-pad">
        <h3 style={H3}>Balances &amp; usage</h3>
        <div className="perf-tiles" style={{ marginTop: 10 }}>
          {['egosms', 'mambosms'].map((p) => {
            const afford = partsAffordable(balances?.[p]?.balance, usage.sms_pricing?.[p]?.cost_per_part_ugx);
            return (
              <div key={p} className="perf-card card-pad perf-tile">
                <span className="perf-tile-label">{PROVIDER_LABEL[p]} balance</span>
                <b style={TILE_VALUE}>{balText(p)}</b>
                <span className="perf-tile-sub">{balances?.[p]?.error ? balances[p].error
                  : afford != null ? `Pays for about ${afford.toLocaleString('en-US')} SMS parts` : 'Set the cost per SMS to see how many parts this pays for'}</span>
              </div>
            );
          })}
          <div className="perf-card card-pad perf-tile">
            <span className="perf-tile-label">SMS budget left</span>
            <b style={{ ...TILE_VALUE, color: budgetLow ? 'var(--danger)' : undefined }}>{usage.budget_total ? usage.budget_left.toLocaleString('en-US') : 'Not set'}</b>
            <span className="perf-tile-sub">{usage.budget_total
              ? `of ${usage.budget_total.toLocaleString('en-US')} SMS · ${usage.budget_pct_left}% left${usage.budget_enforced ? '' : ' · monitor only'}`
              : 'Set a budget in settings below'}</span>
          </div>
        </div>
        <SmsUsageTile hideBudgetLeft />
      </section>

      {/* 2. Compose */}
      <section className="perf-card card-pad">
        <h3 style={H3}>Compose</h3>
        <p className="perf-lead">Choose who receives the message, then write it. Each student gets one SMS, to their first valid number.</p>
        <label style={fieldBox}><span style={lblStyle}>Voting status</span>
          <select className="perf-field" value={voted} onChange={(e) => setVoted(e.target.value)}>
            <option value="any">Everyone</option><option value="voted">Has voted</option><option value="not_voted">Has not voted</option>
          </select></label>
        {fields.map((f) => (
          <label key={f.key} style={fieldBox}><span style={lblStyle}>{f.label} (comma separated, any of)</span>
            <input className="perf-field" value={attrText[f.key] || ''} onChange={(e) => setAttrText({ ...attrText, [f.key]: e.target.value })} /></label>
        ))}
        <label style={fieldBox}><span style={lblStyle}>Specific registration numbers (optional, pasted list)</span>
          <textarea className="perf-field" value={regText} onChange={(e) => setRegText(e.target.value)} /></label>
        <label style={fieldBox}><span style={lblStyle}>Send through</span>
          <select className="perf-field" value={route} onChange={(e) => setRoute(e.target.value)}>
            <option value="default">The usual route (from the routing settings)</option>
            <option value="egosms">EgoSMS only</option>
            <option value="mambosms">MamboSMS only</option>
            <option value="split">Use both: choose the split</option>
          </select></label>
        {route === 'split' && (
          <label style={fieldBox}><span style={lblStyle}>Share sent through EgoSMS (%)</span>
            <input className="perf-field" type="number" min="0" max="100" inputMode="numeric" value={egoPct}
              onChange={(e) => setEgoPct(e.target.value)} />
            <span className="perf-note" style={{ margin: 0 }}>{splitLabel(normalizePct(egoPct))}. The rest goes through MamboSMS. If a provider fails, the message is tried on the other one.</span></label>
        )}
        <label style={fieldBox}><span style={lblStyle}>Message</span>
          <textarea ref={taRef} className="perf-field" value={template} onChange={(e) => setTemplate(e.target.value)} maxLength={1000} /></label>
        <p className="perf-note">Tap a variable to insert it at the cursor.</p>
        <ul className="perf-chips">
          {variables.map((v) => <li key={v}><button type="button" className="perf-btn" onClick={() => insertVar(v)}>{`{${v}}`}</button></li>)}
        </ul>
        {bad.length > 0 && <p className="perf-msg" data-kind="error">Unknown variable: {bad.map((b) => `{${b}}`).join(', ')}. Fix or remove it before sending.</p>}
        {plan && Object.entries(plan.missing || {}).map(([k, n]) => (
          <p key={k} className="perf-note">{n} student{n === 1 ? ' has' : 's have'} no {`{${k}}`}; it will be left empty.</p>
        ))}
        {plan?.samples?.length > 0 && (
          <div>
            <p className="perf-note">Preview with real students:</p>
            {plan.samples.map((s, i) => (
              <div key={i} className="perf-row"><span className="perf-row-title">{s.name || 'Student'}</span><span className="perf-row-text">{s.text}</span></div>
            ))}
          </div>
        )}
      </section>

      {/* 3. Calculator */}
      <section className="perf-card card-pad">
        <h3 style={H3}>Calculator {planBusy && <small className="perf-note"> updating…</small>}</h3>
        <p className="perf-lead">Estimate using {rateLabel} rates. A fallback provider may bill differently.</p>
        {planError && <p className="perf-msg" data-kind="error">{planError}</p>}
        <div className="perf-tiles" style={{ marginTop: 10 }}>
          <div className="perf-card card-pad perf-tile">
            <span className="perf-tile-label">Cost per SMS</span>
            <b style={TILE_VALUE}>{perSms == null ? 'Not set' : ugx(perSms)}</b>
            <span className="perf-tile-sub">{isSplit ? 'Average across both providers' : `${tcount.parts} part${tcount.parts === 1 ? '' : 's'} · ${tcount.chars} characters`}</span>
          </div>
          <div className="perf-card card-pad perf-tile">
            <span className="perf-tile-label">Recipients</span>
            <b style={TILE_VALUE}>{plan ? plan.recipients : '—'}</b>
            <span className="perf-tile-sub">{plan ? `${plan.no_phone} skipped (no phone)` : 'working out…'}</span>
          </div>
          <div className="perf-card card-pad perf-tile">
            <span className="perf-tile-label">Total SMS parts</span>
            <b style={TILE_VALUE}>{plan ? plan.total_parts : '—'}</b>
            <span className="perf-tile-sub">{plan ? (breakdownLabel(plan.by_parts) || '—') : ' '}</span>
          </div>
          <div className="perf-card card-pad perf-tile">
            <span className="perf-tile-label">Total estimated cost</span>
            <b style={TILE_VALUE}>{!plan ? '—' : plan.total_cost == null ? 'Not set' : ugx(plan.total_cost)}</b>
            <span className="perf-tile-sub">{rateLabel} rates · estimate</span>
          </div>
        </div>
        {isSplit && plan?.by_provider && (
          <div className="perf-tiles" style={{ marginTop: 10 }}>
            {Object.entries(plan.by_provider).map(([p, b]) => (
              <div key={p} className="perf-card card-pad perf-tile">
                <span className="perf-tile-label">{PROVIDER_LABEL[p]} share</span>
                <b style={TILE_VALUE}>{b.total_cost == null ? 'Not set' : ugx(b.total_cost)}</b>
                <span className="perf-tile-sub">{b.recipients.toLocaleString('en-US')} SMS · {b.total_parts.toLocaleString('en-US')} parts{b.unit_cost == null ? '' : ` · ${ugx(b.unit_cost)} per part`}</span>
              </div>
            ))}
          </div>
        )}
        <label style={fieldBox}><span style={lblStyle}>What if: cost for a number of people (optional)</span>
          <input className="perf-field" type="number" min="0" inputMode="numeric" value={whatIf} onChange={(e) => setWhatIf(e.target.value)} placeholder="e.g. 500" /></label>
        {whatIfN != null && (
          <div className="perf-tiles" style={{ marginTop: 10 }}>
            <div className="perf-card card-pad perf-tile">
              <span className="perf-tile-label">Cost for {whatIfN} people</span>
              <b style={TILE_VALUE}>{whatIfCost == null ? 'Not set' : ugx(whatIfCost)}</b>
              <span className="perf-tile-sub">{whatIfN} × {perSms == null ? '—' : ugx(perSms)} (template length; variables may change it)</span>
            </div>
          </div>
        )}
        <dl className="perf-kv" style={{ marginTop: 12 }}>
          <dt>Encoding</dt><dd>{tcount.encoding}{tcount.encoding === 'UCS-2' ? ' (smaller limits, can double the cost)' : ''}</dd>
          <dt>Characters left in this part</dt><dd>{tcount.remaining}</dd>
          <dt>Length after variables</dt><dd>{plan?.min_len == null ? '—' : `${plan.min_len} to ${plan.max_len} characters`}</dd>
        </dl>
        {plan && !plan.pricing_set && <p className="perf-msg" data-kind="error">Set the cost per SMS in settings (below) before sending.</p>}
        {short.map((p) => <p key={p} className="perf-msg" data-kind="error">The {PROVIDER_LABEL[p]} share ({ugx(plan.by_provider[p].total_cost)}) is more than its balance ({balances[p].balance}).</p>)}

        <h4 style={{ ...H3, marginTop: 22 }}>System messages</h4>
        <p className="perf-lead">Messages the system sends by itself (voting codes, application updates, login codes). Enter how many of each you expect to see what they cost. Each is counted with its real provider and your longest position title and organisation name.</p>
        {sysError && <p className="perf-msg" data-kind="error">{sysError}</p>}
        {!sysTpl && !sysError && <p className="perf-note">Loading system messages…</p>}
        {sysGroups.map(([group, items]) => (
          <div key={group}>
            <p className="perf-note" style={{ fontWeight: 700 }}>{group}</p>
            {items.map((t) => {
              const r = sys.rows[t.key];
              return (
                <div key={t.key} className="perf-row" style={{ display: 'grid', gap: 4 }}>
                  <span className="perf-row-title">{t.label}</span>
                  <span className="perf-row-text">
                    {t.parts} part{t.parts === 1 ? '' : 's'} · {t.chars} characters · {t.cost_per_sms == null ? 'price not set' : `${ugx(t.cost_per_sms)} each`} · {PROVIDER_LABEL[t.provider]}
                  </span>
                  <span className="perf-note" style={{ margin: 0 }}>{t.when}{t.variants ? ' One of two wordings is sent each time: enter the one that applies.' : ''}</span>
                  <details>
                    <summary className="perf-note" style={{ margin: 0 }}>Show the wording that was counted</summary>
                    <p className="perf-row-text" style={{ margin: '6px 0 0' }}>{t.sample}</p>
                  </details>
                  <label style={fieldBox}><span style={lblStyle}>How many will be sent</span>
                    <input className="perf-field" type="number" min="0" inputMode="numeric" value={qty[t.key] || ''} placeholder="0"
                      onChange={(e) => setQty({ ...qty, [t.key]: e.target.value })} /></label>
                  {t.key === 'otp' && usage.voters > 0 && (
                    <div className="perf-btnbar perf-btnbar-stack">
                      <button type="button" className="perf-btn" onClick={() => setQty({ ...qty, otp: String(usage.voters) })}>Use the voter count ({usage.voters.toLocaleString('en-US')})</button>
                    </div>
                  )}
                  {r.n > 0 && <b>{r.cost == null ? 'Not set' : `${r.n.toLocaleString('en-US')} × ${ugx(t.cost_per_sms)} = ${ugx(r.cost)}`}</b>}
                </div>
              );
            })}
          </div>
        ))}
        {sysTpl && (
          <div className="perf-tiles" style={{ marginTop: 14 }}>
            <div className="perf-card card-pad perf-tile">
              <span className="perf-tile-label">System messages total</span>
              <b style={TILE_VALUE}>{sys.cost == null ? 'Not set' : ugx(sys.cost)}</b>
              <span className="perf-tile-sub">{sys.count.toLocaleString('en-US')} SMS · {sys.parts.toLocaleString('en-US')} parts</span>
            </div>
            <div className="perf-card card-pad perf-tile">
              <span className="perf-tile-label">Everything together</span>
              <b style={TILE_VALUE}>{everything == null ? 'Not set' : ugx(everything)}</b>
              <span className="perf-tile-sub">{campaignIncluded ? 'This campaign plus the system messages' : 'No campaign yet: system messages only'}</span>
            </div>
            {needs.map((n) => {
              const bal = balanceNumber(balances?.[n.p]?.balance);
              const left = n.unpriced || bal == null ? null : bal - n.cost;
              return (
                <div key={n.p} className="perf-card card-pad perf-tile">
                  <span className="perf-tile-label">{PROVIDER_LABEL[n.p]} balance after</span>
                  <b style={{ ...TILE_VALUE, color: left != null && left < 0 ? 'var(--danger)' : undefined }}>{n.unpriced ? 'Not set' : left == null ? '—' : ugx(left)}</b>
                  <span className="perf-tile-sub">{n.unpriced ? 'Set the cost per SMS in settings' : bal == null ? `Needs ${ugx(n.cost)}; balance unknown` : `${ugx(bal)} now, needs ${ugx(n.cost)}`}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 4. Send */}
      <section className="perf-card card-pad">
        <h3 style={H3}>Send</h3>
        <p className="perf-lead">Sending runs in the background and survives a restart. A mistake is billed and cannot be recalled: send a test from Settings to your own number first.</p>
        <label style={fieldBox}><span style={lblStyle}>Reason for sending (required, logged)</span>
          <input className="perf-field" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. reminder: voting closes tomorrow" /></label>
        <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 10 }}>
          <button type="button" className="perf-btn perf-btn-primary" disabled={!canSend} onClick={send}>{sending ? 'Starting…' : 'Send to audience'}</button>
        </div>
        {campaignRunning && <p className="perf-note">Another bulk SMS is still sending.</p>}
        {campaign && (
          <div style={{ marginTop: 12 }}>
            <div className="perf-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <div style={{ width: `${pct}%`, height: '100%', background: 'var(--info)' }} />
            </div>
            <dl className="perf-kv">
              <dt>Status</dt><dd>{campaign.status}</dd>
              <dt>Sent</dt><dd>{campaign.sent} of {campaign.recipients}</dd>
              <dt>Failed</dt><dd>{campaign.failed}</dd>
              <dt>Result unknown</dt><dd>{campaign.ambiguous}</dd>
              <dt>Waiting</dt><dd>{campaign.pending}</dd>
            </dl>
            <div className="perf-btnbar perf-btnbar-stack" style={{ marginTop: 10 }}>
              {campaignActive && <button type="button" className="perf-btn perf-btn-danger" onClick={cancel}>Stop sending</button>}
              {!campaignActive && campaign.failed > 0 && <button type="button" className="perf-btn" onClick={showFailed}>Show failed recipients</button>}
              {!campaignActive && campaign.failed > 0 && <button type="button" className="perf-btn" onClick={retry}>Retry failed only</button>}
            </div>
            {failedRows && (
              <div>{failedRows.length === 0 ? <p className="perf-note">No failed recipients.</p> : failedRows.map((r) => (
                <div key={r.student_id} className="perf-row"><span className="perf-row-title">{r.name || r.student_id}</span><span className="perf-row-text">{r.phone}</span></div>
              ))}</div>
            )}
          </div>
        )}
      </section>

      {/* 5. Settings */}
      <SmsPricingSettings usage={usage} onSaved={load} />
      <SmsRoutingSettings settings={settings} derived={derived} onSaved={load} />
      <SmsTestSettings balances={balances} onBalances={setBalances} />
      <SmsBudgetSettings usage={usage} derived={derived} onSaved={load} />
    </div>
  );
}
