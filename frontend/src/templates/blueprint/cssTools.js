// Test-only helpers for the static CSS tests. Never imported by runtime code.
/* global process */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// vitest runs from frontend/. import.meta.url is not a file: URL under jsdom, so resolve from the project root.
const read = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8');

export const rawCss = read('src/templates/blueprint/blueprint.css');
export const css = rawCss.replace(/\/\*[\s\S]*?\*\//g, '');
export const mock = read('design/blueprint/kes-blueprint-console-mockups.html');
export const legacyCss = read('src/index.css');

export const rules = (src) => [...src.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, sel, body]) => ({ sel: sel.trim(), body }));
export const vars = (body) => Object.fromEntries([...body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)].map(([, k, v]) => [k, v.trim()]));
export const themeVars = (name) =>
  Object.assign({}, ...rules(css).filter((r) => r.sel.includes(`[data-theme="${name}"]`)).map((r) => vars(r.body)));
export const mockVars = (name) => vars(mock.match(new RegExp(`\\.dev\\[data-t=${name}\\]\\{([^}]*)\\}`))[1] + ';'); // last declaration has no trailing ;

// #abc -> #aabbcc (the CSS keeps the mockup's short form; the maths needs six digits)
export const hex6 = (h) => (/^#[0-9a-f]{3}$/i.test(h) ? `#${[...h.slice(1)].map((c) => c + c).join('')}` : h);

// WCAG 2.x relative luminance / contrast ratio for #rrggbb
const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = (h) => { const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b); };
export const ratio = (a, b) => { const [x, y] = [lum(hex6(a)), lum(hex6(b))].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
