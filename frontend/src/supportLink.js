// Voter-facing WhatsApp support link (design Appendix H). Uses the ORG's configured contact, never a
// hardcoded number, and a prefilled message that never asks for the code.
// `contact` is either a number (digits, country code) or a full https WhatsApp link (used as given:
// group and channel links cannot carry a prefilled message).
export function buildSupportLink(contact, orgName, studentId, problem = '') {
  const c = String(contact || '').trim();
  if (!c) return undefined;
  if (/^https:\/\//i.test(c)) return c;
  const digits = c.replace(/\D/g, '');
  if (!digits) return undefined;
  const text = `Hello, I need help with the ${orgName || 'election'} portal. Student ID: ${studentId || ''}. Problem: ${problem || '...'}.`;
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

// Resend deadline survives a page reload: the SERVER decides the wait, the browser only displays it.
const key = (sid) => `resend_deadline:${String(sid || '').trim().toLowerCase()}`;
export function saveResendDeadline(sid, seconds) {
  try { sessionStorage.setItem(key(sid), String(Date.now() + seconds * 1000)); } catch { /* private mode */ }
}
export function loadResendSeconds(sid) {
  try {
    const t = Number(sessionStorage.getItem(key(sid)) || 0);
    return Math.max(0, Math.ceil((t - Date.now()) / 1000));
  } catch { return 0; }
}
export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || '';
export const turnstileConfigured = Boolean(TURNSTILE_SITE_KEY);

export function fmtWait(s) {
  s = Math.max(0, Math.ceil(s));
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.ceil(s / 60)} min`;
  const h = Math.floor(s / 3600), m = Math.ceil((s % 3600) / 60);
  return `${h}h ${m}m`;
}
