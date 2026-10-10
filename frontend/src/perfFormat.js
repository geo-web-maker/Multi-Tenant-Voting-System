// Pure helpers for the superadmin Performance tab (PERF-M6). No DOM, no fetch: unit-tested in perfFormat.test.js.
// Colours are CSS variable names only (P8): the template decides what they look like.

export const STATUS_LABEL = {
  ok: 'OK', busy: 'Busy', critical: 'Critical', throttling: 'Throttling', nodata: 'No data yet', paused: 'Paused', off: 'Off',
};
const STATUS_VAR = {
  ok: '--success', busy: '--warning', critical: '--danger', throttling: '--danger',
  nodata: '--text-muted', paused: '--text-muted', off: '--text-muted',
};
export const statusColorVar = (s) => STATUS_VAR[s] || '--text-muted';

/** Which screen state the summary describes. A cold start never shows a green OK with zero. */
export function viewState(summary) {
  if (!summary) return 'loading';
  if (summary.enabled === false) return 'off';
  if (summary.paused) return 'paused';
  if (summary.ready === false) return 'collecting';
  return summary.status || 'ok';
}

export function fmtOps(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'n/a';
  const n = Number(v);
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
export const fmtMs = (v) => (v === null || v === undefined ? 'n/a' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);
export const fmtMb = (v) => (v === null || v === undefined ? 'n/a' : `${Math.round(v)} MB`);

export function fmtUptime(s) {
  if (s === null || s === undefined) return 'n/a';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function fmtAgo(iso, now = Date.now()) {
  if (!iso) return 'never';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 'never';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Width of the load bar, 0..100. No cap means no bar. */
export function barPct(opsS, cap) {
  if (!cap || opsS === null || opsS === undefined) return null;
  return Math.max(0, Math.min(100, Math.round((opsS / cap) * 100)));
}

export function headerLine(cfg) {
  if (!cfg) return '';
  const tier = cfg.tier === 'custom' ? 'Custom caps' : `${String(cfg.tier || 'free').replace(/^./, (c) => c.toUpperCase())} tier`;
  const ops = cfg.ops_cap ? `cap ${cfg.ops_cap} ops/s` : 'no hard ops cap';
  const conn = cfg.conn_cap ? `${cfg.conn_cap} connections` : 'no connection cap';
  return `${tier} · ${ops} · ${conn}`;
}

export const SOURCE_LABEL = { ui: 'saved here', env: 'environment', preset: 'tier preset' };
export const sourceLabel = (s) => SOURCE_LABEL[s] || '';

export function headroomText(election) {
  const v = election?.voters_per_min_headroom;
  if (v === null || v === undefined) return null;
  return `About ${Math.round(v)} voters per minute before the cap`;
}

export function sinkLine(sink) {
  if (!sink) return '';
  const t = { mongo: 'main cluster', mongo_separate: 'separate cluster', postgres: 'postgres', b2: 'B2 bucket', none: 'off' }[sink.type] || sink.type;
  if (sink.type === 'none') return `History: off${sink.detail ? ` (${sink.detail})` : ''}`;
  return `History: ${t} · last write ${fmtAgo(sink.last_success)} · ${sink.queued || 0} queued${sink.dropped ? ` · ${sink.dropped} dropped` : ''}`;
}
export const sinkIsUnhealthy = (sink) => !!sink && sink.type !== 'none' && (sink.ok === false || (sink.queued || 0) > 3 || (sink.dropped || 0) > 0);

export const PERSIST_OPTIONS = [
  { value: 0, label: 'Off' }, { value: 60, label: '1 min' }, { value: 300, label: '5 min' },
  { value: 900, label: '15 min' }, { value: 3600, label: '60 min' },
];

const wholeIn = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;

/** Turn the settings form (strings) into the API payload plus field errors. Mirrors perf_tiers.validate. */
export function validateSettings(form, presets = []) {
  const errors = {};
  const out = {};
  const num = (x) => (typeof x === 'number' ? x : (String(x).trim() === '' ? NaN : Number(x)));
  const tiers = ['custom', ...presets.map((p) => p.id)];
  if (!tiers.includes(form.tier)) errors.tier = 'Choose a tier.'; else out.tier = form.tier;
  for (const [key, noCap] of [['ops_cap', 'ops_nocap'], ['conn_cap', 'conn_nocap']]) {
    if (form[noCap]) { out[key] = null; continue; }
    const v = num(form[key]);
    if (!wholeIn(v, 1, 100000)) errors[key] = 'Enter a whole number from 1 to 100,000, or choose no hard cap.'; else out[key] = v;
  }
  const w = num(form.warn_pct); const c = num(form.crit_pct);
  if (!wholeIn(w, 1, 99)) errors.warn_pct = 'Enter a whole number from 1 to 99.'; else out.warn_pct = w;
  if (!wholeIn(c, 2, 100)) errors.crit_pct = 'Enter a whole number from 2 to 100.'; else out.crit_pct = c;
  if (!errors.warn_pct && !errors.crit_pct && w >= c) errors.warn_pct = 'Warning must be below critical.';
  const s = num(form.slow_ms);
  if (!wholeIn(s, 10, 10000)) errors.slow_ms = 'Enter a whole number from 10 to 10,000.'; else out.slow_ms = s;
  const p = num(form.persist_s);
  if (!PERSIST_OPTIONS.some((o) => o.value === p)) errors.persist_s = 'Choose Off, 1, 5, 15 or 60 minutes.'; else out.persist_s = p;
  out.paused = !!form.paused;
  return { payload: out, errors, valid: Object.keys(errors).length === 0 };
}

/** Form state from the resolved config. */
export function formFromConfig(cfg) {
  return {
    tier: cfg.tier,
    ops_cap: cfg.ops_cap ?? '', ops_nocap: cfg.ops_cap === null,
    conn_cap: cfg.conn_cap ?? '', conn_nocap: cfg.conn_cap === null,
    warn_pct: cfg.warn_pct, crit_pct: cfg.crit_pct, slow_ms: cfg.slow_ms, persist_s: cfg.persist_s,
    paused: !!cfg.paused,
  };
}

/** Pick a preset: fill the caps from it. Editing a cap by hand switches to Custom, unless it matches the preset. */
export function applyTierChoice(form, tierId, presets) {
  const p = presets.find((x) => x.id === tierId);
  if (!p || tierId === 'custom') return { ...form, tier: 'custom' };
  return { ...form, tier: tierId, ops_cap: p.ops_cap ?? '', ops_nocap: p.ops_cap === null, conn_cap: p.conn_cap ?? '', conn_nocap: p.conn_cap === null };
}
export function editCap(form, patch, presets) {
  const next = { ...form, ...patch };
  const p = presets.find((x) => x.id === form.tier && x.id !== 'custom');
  const same = p && ((next.ops_nocap ? null : Number(next.ops_cap)) === p.ops_cap) && ((next.conn_nocap ? null : Number(next.conn_cap)) === p.conn_cap);
  return { ...next, tier: same ? form.tier : 'custom' };
}

export const formChanged = (a, b) => JSON.stringify(a) !== JSON.stringify(b);
