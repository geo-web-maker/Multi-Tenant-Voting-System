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
} from '../smsCalc';

// The SMS tab: compose to any audience, see the exact cost, send as a background campaign, and every SMS setting.
// Kit classes only, no template branches (docs/UI_TEMPLATE_MANUAL.md). The audience total is computed on the
// server (POST /admin/sms/audience); smsCalc.js only drives the instant preview of one message.

const PROVIDER_LABEL = { egosms: 'EgoSMS', mambosms: 'MamboSMS' };
const fieldBox = { display: 'grid', gap: 4, marginTop: 10 };
const lblStyle = { fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' };
const H3 = { margin: '0 0 6px', fontSize: 15 };
const ACTIVE = ['queued', 'running'];
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
  const [reason, setReason] = useState('');
  const [campaign, setCampaign] = useState(null);
  const [failedRows, setFailedRows] = useState(null);
  const [sending, setSending] = useState(false);
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
  }), [template, voted, attrText, regText]);

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

  const provider = plan?.provider || (usage.sms_route_other === 'mambosms_only' ? 'mambosms' : 'egosms');
  const limits = usage.sms_pricing?.[provider] || {};
  const local = countParts(template, limits);
  const tcount = plan?.template_count || local;
  const bad = unknownTokens(template, variables);
  const unit = plan ? plan.unit_cost : (limits.cost_per_part_ugx ?? null);
  const perSms = costPerSms(tcount.parts, unit);
  const balanceNum = Number(balances?.[provider]?.balance);
  const overBalance = plan?.total_cost != null && Number.isFinite(balanceNum) && plan.total_cost > balanceNum;
  const campaignRunning = Boolean(campaignActive);
  const canSend = Boolean(plan) && !planBusy && !planError && template.trim() && plan.recipients > 0 && plan.pricing_set
    && bad.length === 0 && reason.trim().length >= 3 && !campaignRunning && !sending;

  const insertVar = (name) => {
    const el = taRef.current;
    const r = insertAtCaret(template, `{${name}}`, el?.selectionStart, el?.selectionEnd);
    setTemplate(r.text);
    requestAnimationFrame(() => { if (el) { el.focus(); el.setSelectionRange(r.caret, r.caret); } });
  };

  const send = async () => {
    const msg = `Send this message to ${plan.recipients} student${plan.recipients === 1 ? '' : 's'}?\n\n`
      + `SMS parts: ${plan.total_parts}\nEstimated cost: ${ugx(plan.total_cost)} (${PROVIDER_LABEL[plan.provider]} rates)\nProvider: ${PROVIDER_LABEL[plan.provider]}`
      + `${overBalance ? '\n\nWARNING: this is more than the provider balance.' : ''}\n\nSending cannot be recalled and is billed.`;
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
        <dl className="perf-kv">
          {['egosms', 'mambosms'].map((p) => (
            <React.Fragment key={p}>
              <dt>{PROVIDER_LABEL[p]}</dt>
              <dd>{balances?.[p]?.error ? `— (${balances[p].error})` : `${balances?.[p]?.balance ?? '—'} ${balances?.[p]?.currency || ''}`}</dd>
            </React.Fragment>
          ))}
        </dl>
        <SmsUsageTile />
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
        <p className="perf-lead">Estimate using {PROVIDER_LABEL[provider]} rates. A fallback provider may bill differently.</p>
        {planError && <p className="perf-msg" data-kind="error">{planError}</p>}
        <dl className="perf-kv">
          <dt>Characters (template)</dt><dd>{tcount.chars}</dd>
          <dt>Encoding</dt><dd>{tcount.encoding}{tcount.encoding === 'UCS-2' ? ' (smaller limits, can double the cost)' : ''}</dd>
          <dt>Parts per SMS (template)</dt><dd>{tcount.parts} ({tcount.remaining} characters left in this part)</dd>
          <dt>Provider used for the estimate</dt><dd>{PROVIDER_LABEL[provider]}</dd>
          <dt>Cost per SMS</dt><dd>{perSms == null ? 'Set the cost per SMS in settings' : ugx(perSms)}</dd>
          {plan && (<>
            <dt>Recipients</dt><dd>{plan.recipients}</dd>
            <dt>Students skipped (no phone)</dt><dd>{plan.no_phone}</dd>
            <dt>Length after variables</dt><dd>{plan.min_len == null ? '—' : `${plan.min_len} to ${plan.max_len} characters`}</dd>
            <dt>Breakdown by parts</dt><dd>{breakdownLabel(plan.by_parts) || '—'}</dd>
            <dt>Total SMS parts</dt><dd>{plan.total_parts}</dd>
            <dt>Total estimated cost</dt><dd>{plan.total_cost == null ? 'Set the cost per SMS in settings' : ugx(plan.total_cost)}</dd>
          </>)}
        </dl>
        {plan && !plan.pricing_set && <p className="perf-msg" data-kind="error">Set the cost per SMS in settings (below) before sending.</p>}
        {overBalance && <p className="perf-msg" data-kind="error">The estimated total is more than the {PROVIDER_LABEL[provider]} balance ({balances[provider].balance}).</p>}
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
