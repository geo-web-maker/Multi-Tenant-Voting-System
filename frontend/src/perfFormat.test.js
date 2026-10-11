import { describe, it, expect } from 'vitest';
import {
  viewState, fmtOps, fmtMs, fmtUptime, fmtAgo, barPct, headerLine, headroomText, sinkLine, sinkIsUnhealthy,
  validateSettings, formFromConfig, applyTierChoice, editCap, formChanged, statusColorVar, clockLabel, tickIndexes,
} from './perfFormat';

const presets = [{ id: 'free', ops_cap: 100, conn_cap: 500 }, { id: 'custom', ops_cap: null, conn_cap: null }];
const cfg = { tier: 'free', ops_cap: 100, conn_cap: 500, warn_pct: 70, crit_pct: 90, slow_ms: 250, persist_s: 300, paused: false };

describe('viewState', () => {
  it('covers every screen state', () => {
    expect(viewState(null)).toBe('loading');
    expect(viewState({ enabled: false })).toBe('off');
    expect(viewState({ enabled: true, paused: true })).toBe('paused');
    expect(viewState({ enabled: true, ready: false })).toBe('collecting');
    expect(viewState({ enabled: true, ready: true, status: 'critical' })).toBe('critical');
    expect(viewState({ enabled: true, ready: true, status: 'throttling' })).toBe('throttling');
  });
  it('a cold start is never green', () => { expect(viewState({ enabled: true, ready: false, status: 'ok' })).not.toBe('ok'); });
});

describe('formatters', () => {
  it('formats numbers and times', () => {
    expect(fmtOps(37)).toBe('37'); expect(fmtOps(31.44)).toBe('31.4'); expect(fmtOps(null)).toBe('n/a');
    expect(fmtMs(14)).toBe('14 ms'); expect(fmtMs(1500)).toBe('1.5 s'); expect(fmtMs(null)).toBe('n/a');
    expect(fmtUptime(5321)).toBe('1h 28m'); expect(fmtUptime(45)).toBe('45s');
    expect(fmtAgo(null)).toBe('never');
    expect(fmtAgo('2026-10-10T10:00:00Z', new Date('2026-10-10T10:02:30Z').getTime())).toBe('2 min ago');
  });
  it('bar width is clamped and absent without a cap', () => {
    expect(barPct(37, 100)).toBe(37); expect(barPct(250, 100)).toBe(100); expect(barPct(5, null)).toBeNull();
  });
  it('status colours are variable names, never hex', () => {
    for (const s of ['ok', 'busy', 'critical', 'throttling', 'nodata', 'paused', 'off']) expect(statusColorVar(s)).toMatch(/^--[a-z-]+$/);
  });
});

describe('header, headroom and sink lines', () => {
  it('states the cap in use', () => {
    expect(headerLine(cfg)).toBe('Free tier · cap 100 ops/s · 500 connections');
    expect(headerLine({ ...cfg, tier: 'custom', ops_cap: null })).toBe('Custom caps · no hard ops cap · 500 connections');
  });
  it('headroom hides when absent', () => {
    expect(headroomText({ voters_per_min_headroom: 140.4 })).toBe('About 140 voters per minute before the cap');
    expect(headroomText({ voters_per_min_headroom: null })).toBeNull();
  });
  it('sink line and health', () => {
    const ok = { type: 'postgres', ok: true, last_success: null, queued: 0, dropped: 0 };
    expect(sinkLine(ok)).toContain('postgres');
    expect(sinkIsUnhealthy(ok)).toBe(false);
    expect(sinkIsUnhealthy({ ...ok, queued: 5 })).toBe(true);
    expect(sinkIsUnhealthy({ ...ok, dropped: 1 })).toBe(true);
    expect(sinkIsUnhealthy({ type: 'none' })).toBe(false);
  });
});

describe('settings form', () => {
  it('a clean form is valid and unchanged', () => {
    const f = formFromConfig(cfg);
    expect(validateSettings(f, presets).valid).toBe(true);
    expect(formChanged(f, formFromConfig(cfg))).toBe(false);
  });
  it('rejects what the server rejects', () => {
    const f = formFromConfig(cfg);
    expect(validateSettings({ ...f, warn_pct: 95, crit_pct: 90 }, presets).errors.warn_pct).toMatch(/below critical/);
    expect(validateSettings({ ...f, ops_cap: 0 }, presets).errors.ops_cap).toBeTruthy();
    expect(validateSettings({ ...f, ops_cap: '12.5' }, presets).errors.ops_cap).toBeTruthy();
    expect(validateSettings({ ...f, slow_ms: 5 }, presets).errors.slow_ms).toBeTruthy();
    expect(validateSettings({ ...f, persist_s: 7 }, presets).errors.persist_s).toBeTruthy();
    expect(validateSettings({ ...f, tier: 'gold' }, presets).errors.tier).toBeTruthy();
  });
  it('no hard cap sends null', () => {
    const r = validateSettings({ ...formFromConfig(cfg), ops_nocap: true }, presets);
    expect(r.valid).toBe(true); expect(r.payload.ops_cap).toBeNull();
  });
  it('editing a cap switches to Custom unless it matches the preset', () => {
    const f = formFromConfig(cfg);
    expect(editCap(f, { ops_cap: 150 }, presets).tier).toBe('custom');
    expect(editCap(f, { ops_cap: 100 }, presets).tier).toBe('free');
  });
  it('choosing a preset fills the caps', () => {
    const f = applyTierChoice({ ...formFromConfig(cfg), tier: 'custom', ops_cap: 250 }, 'free', presets);
    expect(f.tier).toBe('free'); expect(f.ops_cap).toBe(100); expect(f.conn_cap).toBe(500);
  });
});

describe('chart axis helpers', () => {
  it('clockLabel shows HH:MM for short ranges and D/M for 7 days, in the given zone', () => {
    const t = Date.UTC(2026, 9, 11, 9, 5) / 1000;            // 09:05 UTC = 12:05 in Kampala
    expect(clockLabel(t, '15m', 'Africa/Kampala')).toBe('12:05');
    expect(clockLabel(t, '24h', 'UTC')).toBe('09:05');
    expect(clockLabel(t, '7d', 'UTC')).toBe('11/10');
    expect(clockLabel(NaN, '15m')).toBe('');
  });
  it('tickIndexes spreads ticks without duplicates', () => {
    expect(tickIndexes(0)).toEqual([]);
    expect(tickIndexes(1)).toEqual([0]);
    expect(tickIndexes(9, 4)).toEqual([0, 2, 4, 6, 8]);
    expect(tickIndexes(3, 4)).toEqual([0, 1, 2]);
  });
});
