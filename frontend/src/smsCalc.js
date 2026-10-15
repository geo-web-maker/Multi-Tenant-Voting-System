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
