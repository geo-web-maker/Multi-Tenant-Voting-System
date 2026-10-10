import React, { useEffect, useMemo, useState } from 'react';
import api, { getErrorMessage } from '../api';
import { useToast, useConfirm } from './UIFeedback';
import {
  PERSIST_OPTIONS, applyTierChoice, editCap, formChanged, formFromConfig, sourceLabel, validateSettings,
} from '../perfFormat';

const field = { display: 'grid', gap: 4, marginBottom: 12 };
const input = { padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', font: 'inherit', minWidth: 0 };
const err = { color: 'var(--danger)', fontSize: 13, margin: 0 };
const hint = { color: 'var(--text-muted)', fontSize: 12, margin: 0 };

function Field({ id, label, source, error, children }) {
  return (
    <div style={field}>
      <label htmlFor={id} style={{ fontWeight: 600, fontSize: 14 }}>
        {label}{source ? <span style={{ ...hint, marginLeft: 8, fontWeight: 400 }}>{sourceLabel(source)}</span> : null}
      </label>
      {children}
      {error ? <p style={err} role="alert">{error}</p> : null}
    </div>
  );
}

/** Settings card (guide 2.5). Collapsed by default. Caps, thresholds and the pause switch live in the database. */
export default function PerformanceSettings({ config, onSaved }) {
  const toast = useToast();
  const confirm = useConfirm();
  const presets = config?.presets || [];
  const base = useMemo(() => (config ? formFromConfig(config) : null), [config]);
  const [form, setForm] = useState(base);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm(base); }, [base]);
  if (!config || !form) return null;

  const { payload, errors, valid } = validateSettings(form, presets);
  const changed = formChanged(form, base);
  const src = config.sources || {};
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.put('/superadmin/performance/config', payload);
      toast('Performance settings saved.', { kind: 'success' });
      onSaved?.(r.data);
    } catch (e) {
      toast(getErrorMessage(e, 'Could not save the settings.'), { kind: 'error' });
    } finally { setBusy(false); }
  };
  const reset = async () => {
    const ok = await confirm('Reset to defaults? Saved values are removed and the environment variables and tier preset apply again.', { confirmText: 'Reset' });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.post('/superadmin/performance/config/reset');
      toast('Settings reset to defaults.', { kind: 'success' });
      onSaved?.(r.data);
    } catch (e) {
      toast(getErrorMessage(e, 'Could not reset the settings.'), { kind: 'error' });
    } finally { setBusy(false); }
  };

  return (
    <section className="perf-card card-pad" aria-label="Performance settings">
      <button type="button" className="perf-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? 'Hide settings' : 'Settings'}
      </button>
      {open && (
        <div style={{ marginTop: 12 }}>
          <Field id="perf-tier" label="Tier" source={src.ops_cap} error={errors.tier}>
            <select id="perf-tier" className="perf-field" style={input} value={form.tier}
              onChange={(e) => setForm(applyTierChoice(form, e.target.value, presets))}>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.id === 'custom' ? 'Custom' : p.id}</option>)}
            </select>
          </Field>
          <p style={hint}>{config.note} <a href="https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/" target="_blank" rel="noreferrer">Check these against your Atlas plan</a> (presets last verified {config.presets_verified_on}).</p>

          <Field id="perf-ops" label="Ops cap (operations per second)" source={src.ops_cap} error={errors.ops_cap}>
            <input id="perf-ops" className="perf-field" style={input} inputMode="numeric" disabled={form.ops_nocap}
              value={form.ops_nocap ? '' : form.ops_cap} onChange={(e) => setForm(editCap(form, { ops_cap: e.target.value }, presets))} />
            <label className="perf-check"><input type="checkbox" checked={form.ops_nocap}
              onChange={(e) => setForm(editCap(form, { ops_nocap: e.target.checked }, presets))} /> No hard cap</label>
          </Field>
          <Field id="perf-conn" label="Connection cap" source={src.conn_cap} error={errors.conn_cap}>
            <input id="perf-conn" className="perf-field" style={input} inputMode="numeric" disabled={form.conn_nocap}
              value={form.conn_nocap ? '' : form.conn_cap} onChange={(e) => setForm(editCap(form, { conn_cap: e.target.value }, presets))} />
            <label className="perf-check"><input type="checkbox" checked={form.conn_nocap}
              onChange={(e) => setForm(editCap(form, { conn_nocap: e.target.checked }, presets))} /> No hard cap</label>
          </Field>
          <Field id="perf-warn" label="Warn at (% of cap)" source={src.warn_pct} error={errors.warn_pct}>
            <input id="perf-warn" className="perf-field" style={input} inputMode="numeric" value={form.warn_pct} onChange={(e) => set({ warn_pct: e.target.value })} />
          </Field>
          <Field id="perf-crit" label="Critical at (% of cap)" source={src.crit_pct} error={errors.crit_pct}>
            <input id="perf-crit" className="perf-field" style={input} inputMode="numeric" value={form.crit_pct} onChange={(e) => set({ crit_pct: e.target.value })} />
          </Field>
          <Field id="perf-slow" label="Slow command (ms)" source={src.slow_ms} error={errors.slow_ms}>
            <input id="perf-slow" className="perf-field" style={input} inputMode="numeric" value={form.slow_ms} onChange={(e) => set({ slow_ms: e.target.value })} />
          </Field>
          <Field id="perf-persist" label="History write interval" source={src.persist_s} error={errors.persist_s}>
            <select id="perf-persist" className="perf-field" style={input} value={form.persist_s} onChange={(e) => set({ persist_s: Number(e.target.value) })}>
              {PERSIST_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          <label className="perf-check" style={{ marginBottom: 12 }}>
            <input type="checkbox" checked={form.paused} onChange={(e) => set({ paused: e.target.checked })} /> Pause collection
          </label>
          <p style={hint}>Pausing stops measuring and history writes. A full off needs PERF_ENABLED=false and a restart.</p>
          <div className="perf-actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            <button type="button" className="perf-btn" onClick={save} disabled={!valid || !changed || busy}>Save</button>
            <button type="button" className="perf-btn" onClick={reset} disabled={busy}>Reset to defaults</button>
          </div>
        </div>
      )}
    </section>
  );
}
