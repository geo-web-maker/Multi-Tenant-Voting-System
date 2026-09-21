// Voter-facing WhatsApp support link (design Appendix H). Uses the ORG's support_phone, never a hardcoded
// number, and a prefilled message that never asks for the code.
export function buildSupportLink(supportPhone, orgName, studentId, problem = '') {
  if (!supportPhone) return undefined;
  const text = `Hello, I need help with the ${orgName || 'election'} portal. Student ID: ${studentId || ''}. Problem: ${problem || '...'}.`;
  return `https://wa.me/${supportPhone}?text=${encodeURIComponent(text)}`;
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
