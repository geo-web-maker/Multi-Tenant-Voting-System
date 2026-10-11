import { properName } from './displayText';

// Printed certificate looks an organisation can choose. The ids must match DOCUMENT_TEMPLATES in backend/main.py.
// A missing or unknown id always means "classic": that is how every certificate issued before the choice existed was printed.
export const DOCUMENT_TEMPLATES = [
  { id: 'classic', label: 'Classic', landscape: false, hint: 'Gold double border, serif type, centred. Prints portrait.' },
  { id: 'formal', label: 'Formal digital seal', landscape: true, hint: 'Framed in your brand colour with a digital seal carrying the organisation name, a QR code and the issue time. Prints landscape.' },
];

export const resolveDocTemplate = (id) => (DOCUMENT_TEMPLATES.some((t) => t.id === id) ? id : 'classic');
export const isLandscape = (id) => DOCUMENT_TEMPLATES.find((t) => t.id === resolveDocTemplate(id)).landscape;

// Default "Save as PDF" name: person - document - organisation.
export function docFileName(docName, name, orgName) {
  const clean = (t) => String(t || '').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim();
  return [properName(clean(name)), clean(docName), clean(orgName)].filter(Boolean).join(' - ');
}

// Organisation colours on a white sheet: text colour must be dark enough to read, rules and rings must be visible.
const parseHex = (hex) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const luminance = ([r, g, b]) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
const toHex = (c) => `#${c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;

export function sealInk(hex, fallback = '#14305a') {
  const c = parseHex(hex);
  return c && luminance(c) <= 0.45 ? toHex(c) : fallback;
}

export function sealAccent(hex, fallback = '#b8860b') {
  const c = parseHex(hex);
  if (!c) return fallback;
  return luminance(c) > 0.6 ? toHex(c.map((v) => v * 0.65)) : toHex(c);
}
