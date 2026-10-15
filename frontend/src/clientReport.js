// Voter-side problem reports. Tells the server about failures it cannot see itself: a blocked bot-check script, a widget
// error, a bot check that never returns a token, a JavaScript crash. Nothing personal is ever sent: only the problem type,
// a short code, the page the voter was on and a short error text. The browser family comes from the User-Agent on the server.
// Best effort: it never throws, never blocks and never retries, so it cannot make a bad situation worse.
import { API_BASE, ORG_SLUG, SUPERADMIN_ORG_OVERRIDE_KEY } from './api';

const MAX_PER_PAGE_LOAD = 8;
const REPEAT_GAP_MS = 60000;
let sent = 0;
let step = 'other';
const lastAt = new Map();

/** The page the voter is on (same names as analytics, e.g. voter_identity). */
export function setReportStep(name) { if (name) step = String(name).slice(0, 30); }

const isStaff = () => { try { return Boolean(sessionStorage.getItem('admin_token')); } catch { return false; } };
const slug = () => { try { return sessionStorage.getItem(SUPERADMIN_ORG_OVERRIDE_KEY) || ORG_SLUG; } catch { return ORG_SLUG; } };

export function reportClientProblem(kind, { code = '', detail = '' } = {}) {
  try {
    if (!slug() || isStaff() || sent >= MAX_PER_PAGE_LOAD) return;
    const key = `${kind}|${code}`;
    const now = Date.now();
    if (now - (lastAt.get(key) || 0) < REPEAT_GAP_MS) return;
    lastAt.set(key, now);
    sent += 1;
    fetch(`${API_BASE}/client-report`, {
      method: 'POST', keepalive: true,
      headers: { 'Content-Type': 'application/json', 'X-Org-Slug': slug() },
      body: JSON.stringify({ kind, code: String(code).slice(0, 60), step, detail: String(detail).slice(0, 120) }),
    }).catch(() => {});
  } catch { /* reporting must never break the page */ }
}

// Browser noise that says nothing about our site.
const IGNORED = /ResizeObserver loop|^Script error\.?$|Non-Error promise rejection/i;
const text = (v) => (v && (v.message || String(v))) || '';

let installed = false;
export function initClientReporting() {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.addEventListener('error', (e) => {
    const msg = text(e.error) || e.message || '';
    if (!msg || IGNORED.test(msg)) return;
    reportClientProblem('js_error', { code: String(msg).slice(0, 60), detail: msg });
  });
  window.addEventListener('unhandledrejection', (e) => {
    const msg = text(e.reason);
    if (!msg || IGNORED.test(msg)) return;
    reportClientProblem('unhandled_rejection', { code: msg.slice(0, 60), detail: msg });
  });
}
