// Organisation branding -> CSS variables, for BOTH templates (default and blueprint).
//
// An org picks two colours (primary, accent). Anything an org can type into a colour box is not automatically
// readable, so the raw colours are never the only thing the UI sees. This module writes, inline on <html>:
//
//   --brand-primary / --brand-accent          the raw colours (use as a FILL)
//   --brand-on-primary / --brand-on-accent    best ink (white or near-black) for text on those fills
//   --brand-stripe                            a visible edge to sit beside an accent fill
//   --brand-primary-ui / --brand-accent-ui    the same hue nudged (lightness only) until it reads >= 4.5:1 on the
//                                             current card surfaces, for TEXT / outlines / ticks
//   --bp-ac / --bp-ai                         accent-ui + its ink: the single accent the blueprint template
//                                             (and every `var(--bp-ac, <fallback>)` in screen code) draws with
//   --bp-tint / --bp-tint2 / --bp-ac-edge     the accent mixed into the card surface (10% / 18%) and at 60% alpha
//
// The *-ui family depends on the theme (light cards vs dark cards), so it is recomputed whenever
// <html data-theme> or data-template changes. Nothing here is a colour decision of its own: with no (or an
// unparseable) brand colour every derived variable is removed and the stylesheet defaults apply.

const WHITE = '#ffffff';
const DARK_INK = '#0b1220';
const MIN_TEXT = 4.5;

// Card surfaces the accent must read on, per template and theme (blueprint values mirror blueprint.css section 1).
const SURFACES = {
  blueprint: {
    light: { card: '#ffffff', all: ['#ffffff', '#f1f3f5', '#e9ecef'] },
    dark: { card: '#10335f', all: ['#10335f', '#0d2b52', '#143b6e', '#0b2545'] },
  },
  default: {
    light: { card: '#ffffff', all: ['#ffffff', '#f0f1f3', '#fafafa'] },
    dark: { card: '#1a2030', all: ['#1a2030', '#242b3d', '#0f1420'] },
  },
};

const OWNED = [
  '--brand-primary', '--brand-accent', '--brand-on-primary', '--brand-on-accent', '--brand-stripe',
  '--brand-primary-ui', '--brand-accent-ui', '--bp-ac', '--bp-ai', '--bp-tint', '--bp-tint2', '--bp-ac-edge',
];

/* ---------- colour maths (WCAG 2.x) ---------- */

export function parseHex(v) {
  if (typeof v !== 'string') return null;
  const m = v.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}
export const toHex = (rgb) => `#${rgb.map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, '0')).join('')}`;

const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = (rgb) => 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
export function contrast(a, b) {
  const [x, y] = [lum(parseHex(a)), lum(parseHex(b))].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}
function hslToRgb([h, s, l]) {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => {
    t = (t + 1) % 1;
    const v = t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p;
    return v * 255;
  };
  return [f(h + 1 / 3), f(h), f(h - 1 / 3)];
}

/** White or near-black, whichever reads better on `bg`. */
export const inkOn = (bg) => (contrast(WHITE, bg) >= contrast(DARK_INK, bg) ? WHITE : DARK_INK);

/**
 * Same hue and saturation, lightness moved only as far as needed so `hex` reaches `min`:1 against EVERY surface.
 * Moves toward the pole (black or white) that is further from the surfaces; returns the input untouched if it already passes.
 */
export function ensureContrast(hex, surfaces, min = MIN_TEXT) {
  const rgb = parseHex(hex);
  const ok = (h) => surfaces.every((s) => contrast(h, s) >= min);
  if (!rgb || ok(hex)) return hex;
  const avg = surfaces.reduce((n, s) => n + lum(parseHex(s)), 0) / surfaces.length;
  const dir = avg > 0.4 ? -1 : 1; // light cards -> go darker, dark cards -> go lighter
  const [h, s, l] = rgbToHsl(rgb);
  for (let step = 1; step <= 100; step++) {
    const nl = l + dir * step * 0.01;
    if (nl < 0 || nl > 1) break;
    const cand = toHex(hslToRgb([h, s, nl]));
    if (ok(cand)) return cand;
  }
  return dir < 0 ? '#000000' : WHITE;
}

const mix = (a, b, pa) => toHex(parseHex(a).map((c, i) => c * pa + parseHex(b)[i] * (1 - pa)));

/**
 * Pure derivation. `primary` / `accent` are hex strings (anything else is skipped); `template` is 'default' | 'blueprint';
 * `theme` is 'light' | 'dark'. Returns { '--css-var': value }.
 */
export function deriveBrandVars({ primary, accent, template = 'default', theme = 'light' }) {
  const surf = (SURFACES[template] || SURFACES.default)[theme === 'dark' ? 'dark' : 'light'];
  const out = {};
  const p = parseHex(primary) ? toHex(parseHex(primary)) : null;
  const a = parseHex(accent) ? toHex(parseHex(accent)) : null;

  if (p) {
    out['--brand-on-primary'] = inkOn(p);
    out['--brand-primary-ui'] = ensureContrast(p, surf.all);
  }
  if (a) {
    out['--brand-on-accent'] = inkOn(a);
    out['--brand-accent-ui'] = ensureContrast(a, surf.all);
    // a visible edge beside an accent fill: the primary if it separates from the accent, else the accent darkened
    out['--brand-stripe'] = p && contrast(p, a) >= 1.8 ? p : mix(a, '#000000', 0.55);
  }
  // The template accent: the accent colour (primary if no accent was set), surface-safe, with its own ink.
  const base = a || p;
  if (base) {
    const ac = ensureContrast(base, surf.all);
    out['--bp-ac'] = ac;
    out['--bp-ai'] = inkOn(ac);
    out['--bp-tint'] = mix(ac, surf.card, 0.1);
    out['--bp-tint2'] = mix(ac, surf.card, 0.18);
    const [r, g, b] = parseHex(ac);
    out['--bp-ac-edge'] = `rgb(${r} ${g} ${b} / .6)`;
  }
  return out;
}

/* ---------- applying it to <html> ---------- */

let current = { primary: '', accent: '' };
let watching = false;

const currentTheme = (el) => {
  const t = el.getAttribute('data-theme');
  if (t === 'light' || t === 'dark') return t;
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

export function applyBrand(root = typeof document !== 'undefined' ? document.documentElement : null) {
  if (!root) return;
  const { primary, accent } = current;
  const template = root.dataset.template === 'blueprint' ? 'blueprint' : 'default';
  const vars = deriveBrandVars({ primary, accent, template, theme: currentTheme(root) });
  // raw colours: kept exactly as typed (a CSS name such as "rebeccapurple" still works as a fill)
  if (primary) root.style.setProperty('--brand-primary', primary); else root.style.removeProperty('--brand-primary');
  if (accent) root.style.setProperty('--brand-accent', accent); else root.style.removeProperty('--brand-accent');
  for (const k of OWNED) {
    if (k === '--brand-primary' || k === '--brand-accent') continue;
    if (vars[k]) root.style.setProperty(k, vars[k]); else root.style.removeProperty(k);
  }
}

/** Single entry point: boot (App) and the Branding tab's Save both call this. Empty values fall back to the stylesheet. */
export function setBrand({ primary_color, accent_color } = {}) {
  current = { primary: (primary_color || '').trim(), accent: (accent_color || '').trim() };
  applyBrand();
  if (!watching && typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
    watching = true;
    // light <-> dark and template switches change which surfaces the accent must read on
    new MutationObserver(() => applyBrand()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-template'] });
  }
}
