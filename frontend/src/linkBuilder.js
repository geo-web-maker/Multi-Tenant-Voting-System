// D2c (WP-9.2): tagged share links, https://<host>/?src=<tag>. Pure; the tag rule mirrors the tracker and the backend.
export const CHANNELS = ['whatsapp', 'facebook', 'class-group', 'poster-qr', 'sms'];
export const TAG_RE = /^[a-z0-9_-]{2,40}$/;

const cleanHost = (host) => String(host ?? '').trim().replace(/^https?:\/\//i, '').replace(/\/+$/, '');

// Returns { ok: true, url } or { ok: false, error }. `tag` is a channel name or a custom tag.
export function buildTaggedLink(host, tag) {
  const h = cleanHost(host);
  if (!h || /[\s/?#]/.test(h)) return { ok: false, error: 'No valid site address.' };
  const t = String(tag ?? '').trim();
  if (!TAG_RE.test(t)) return { ok: false, error: 'Use 2 to 40 lower-case letters, digits, - or _.' };
  return { ok: true, url: `https://${h}/?src=${t}` };
}
