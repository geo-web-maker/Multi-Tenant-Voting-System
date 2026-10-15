// Pure SMS counting, variable and cost helpers for the Bulk SMS tab.
// Twin of backend/sms_bulk.py: the backend is the source of truth for the audience total, this file is for the
// live preview of one message. Both use the same test vectors (smsCalc.test.js / tests/test_sms_bulk.py).

export const DEFAULT_LIMITS = { single_limit: 160, multi_limit: 153, unicode_single_limit: 70, unicode_multi_limit: 67 };
export const BASE_VARIABLES = ['name', 'first_name', 'reg_no'];

const GSM_BASIC = new Set(Array.from(
  '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà',
));
const GSM_EXT = new Set(Array.from('^{}\\[]~|€\f'));

/** { chars, encoding, parts, remaining }. Extended GSM characters count 2; any non-GSM character makes the whole message UCS-2. */
export function countParts(text, limits) {
  const lim = { ...DEFAULT_LIMITS, ...(limits || {}) };
  const chars = Array.from(text || '');
  const gsm = chars.every((c) => GSM_BASIC.has(c) || GSM_EXT.has(c));
  let units; let single; let multi; let encoding;
  if (gsm) {
    encoding = 'GSM-7';
    units = chars.reduce((n, c) => n + (GSM_EXT.has(c) ? 2 : 1), 0);
    single = lim.single_limit; multi = lim.multi_limit;
  } else {
    encoding = 'UCS-2';
    units = chars.reduce((n, c) => n + (c.codePointAt(0) > 0xffff ? 2 : 1), 0);
    single = lim.unicode_single_limit; multi = lim.unicode_multi_limit;
  }
  if (units === 0) return { chars: 0, encoding, parts: 0, remaining: single };
  if (units <= single) return { chars: units, encoding, parts: 1, remaining: single - units };
  const parts = Math.ceil(units / multi);
  return { chars: units, encoding, parts, remaining: parts * multi - units };
}

export const variableNames = (fieldKeys = []) => [...BASE_VARIABLES, ...fieldKeys.filter((k) => !BASE_VARIABLES.includes(k))];

export function unknownTokens(template, known) {
  const ok = new Set(known);
  const bad = [];
  for (const m of (template || '').matchAll(/\{([A-Za-z0-9_]+)\}/g)) if (!ok.has(m[1]) && !bad.includes(m[1])) bad.push(m[1]);
  return bad;
}

/** Plain replace over a known list (no evaluator). */
export function renderTemplate(template, values) {
  let out = template || '';
  for (const [k, v] of Object.entries(values || {})) out = out.split(`{${k}}`).join(v ?? '');
  return out;
}

/** Insert `token` at the caret of a textarea value; returns { text, caret }. */
export function insertAtCaret(text, token, start, end) {
  const s = Math.max(0, Math.min(start ?? text.length, text.length));
  const e = Math.max(s, Math.min(end ?? s, text.length));
  return { text: text.slice(0, s) + token + text.slice(e), caret: s + token.length };
}

/** "480 × 1 part, 20 × 2 parts" */
export function breakdownLabel(byParts) {
  return Object.entries(byParts || {}).map(([p, n]) => `${n} × ${p} part${Number(p) === 1 ? '' : 's'}`).join(', ');
}

export const ugx = (n) => (n == null ? '—' : `UGX ${Math.round(n * 100) / 100 === Math.round(n) ? Math.round(n).toLocaleString('en-US') : Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })}`);

/** Cost of one SMS of `parts` parts, or null when the price is not set (never 0). */
export const costPerSms = (parts, costPerPart) => (costPerPart == null || costPerPart === '' ? null : parts * Number(costPerPart));

/** A typed quantity as a whole number >= 0 (blank, negative or junk is 0). */
export const toCount = (v) => { const n = Math.floor(Number(v)); return Number.isFinite(n) && n > 0 ? n : 0; };

/** A provider balance as a number, or null when it is missing or not numeric ("12,500.50" is fine). */
export const balanceNumber = (b) => {
  if (b == null || b === '') return null;
  const n = Number(String(b).replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
};

/** Whole SMS parts a balance still pays for at `costPerPart`, or null when either is unknown. */
export const partsAffordable = (balance, costPerPart) => {
  const bal = balanceNumber(balance);
  const unit = costPerPart == null || costPerPart === '' ? null : Number(costPerPart);
  return bal == null || unit == null || !(unit > 0) ? null : Math.max(0, Math.floor(bal / unit));
};

/**
 * Totals for the system messages (/admin/sms/templates) given how many of each the person expects to send.
 * `qty` is { [key]: typed text }. A send whose price is not set makes the total null (never a lower number),
 * and `byProvider` lets the caller compare each provider's need with its balance.
 * Returns { rows: {key: {n, parts, cost}}, count, parts, cost, unpriced, byProvider: {p: {parts, cost, unpriced}} }.
 */
export function systemTotals(templates, qty) {
  const rows = {};
  const byProvider = {};
  let count = 0; let parts = 0; let cost = 0; let unpriced = false;
  for (const t of templates || []) {
    const n = toCount(qty?.[t.key]);
    const rowCost = t.cost_per_sms == null ? null : t.cost_per_sms * n;
    rows[t.key] = { n, parts: n * t.parts, cost: n ? rowCost : 0 };
    if (!n) continue;
    count += n; parts += n * t.parts;
    const b = byProvider[t.provider] || (byProvider[t.provider] = { parts: 0, cost: 0, unpriced: false });
    b.parts += n * t.parts;
    if (rowCost == null) { b.unpriced = true; unpriced = true; } else { b.cost += rowCost; cost += rowCost; }
  }
  return { rows, count, parts, cost: unpriced ? null : cost, unpriced, byProvider };
}

/** The share of a bulk send that goes through EgoSMS, as a whole number from 0 to 100 (blank or junk gives `fallback`). */
export const normalizePct = (v, fallback = 50) => {
  const n = Math.floor(Number(v));
  return v === '' || v == null || !Number.isFinite(n) ? fallback : Math.min(100, Math.max(0, n));
};

/** "EgoSMS 30% · MamboSMS 70%" */
export const splitLabel = (egoPct) => `EgoSMS ${egoPct}% · MamboSMS ${100 - egoPct}%`;

/**
 * Providers whose balance is lower than what a send would cost them.
 * `byProvider` is the server's { egosms: {total_cost}, mambosms: {total_cost} }; a provider whose cost or balance
 * is unknown is never reported (we cannot say it falls short).
 */
export const shortfalls = (byProvider, balances) => Object.entries(byProvider || {}).filter(([p, b]) => {
  const bal = balanceNumber(balances?.[p]?.balance);
  return b && b.total_cost != null && bal != null && b.total_cost > bal;
}).map(([p]) => p);
