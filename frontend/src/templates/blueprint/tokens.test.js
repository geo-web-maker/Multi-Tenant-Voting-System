import { describe, it, expect } from 'vitest';
import { rawCss, css, legacyCss, themeVars as rawThemeVars, mockVars, vars, rules, hex6 } from './cssTools.js';

const themeVars = (n) => Object.fromEntries(Object.entries(rawThemeVars(n)).map(([k, v]) => [k, hex6(v)]));

const REQUIRED = ['bg','sf','sf2','sf3','line','line-ui','tx','mu','ac','ai','ok','wn','no','grid','sh','tint','tint2','ok-tint','wn-tint','no-tint','mu-tint','ac-edge','ok-edge','wn-edge','no-edge','mu-edge'];
const SHARED = ['bg','sf','sf2','sf3','line','tx','mu','ac','ai','ok','wn','no','grid']; // same name in the mockup (minus --bp-)

for (const theme of ['light', 'dark']) {
  describe(`tokens (${theme})`, () => {
    const t = themeVars(theme);
    const m = mockVars(theme);
    it('defines every required token', () => { for (const k of REQUIRED) expect(t[`bp-${k}`], k).toBeTruthy(); });
    it('matches the mockup values (drift guard)', () => {
      for (const k of SHARED) expect(t[`bp-${k}`].replace(/\s/g, ''), k).toBe(hex6(m[k].replace(/\s/g, '')));
    });
    it('precomputed tints equal the mockup color-mix result (±1/channel)', () => {
      const ch = (hex, i) => parseInt(hex.slice(1 + i, 3 + i), 16);
      const mix = (a, b, p) => [0, 2, 4].map((i) => Math.round(ch(a, i) * p + ch(b, i) * (1 - p)));
      const close = (hex, rgb) => [0, 2, 4].every((i, j) => Math.abs(ch(hex, i) - rgb[j]) <= 1);
      expect(close(t['bp-tint'], mix(t['bp-ac'], t['bp-sf'], 0.1))).toBe(true);
      expect(close(t['bp-tint2'], mix(t['bp-ac'], t['bp-sf'], 0.18))).toBe(true);
      for (const k of ['ok', 'wn', 'no', 'mu']) expect(close(t[`bp-${k}-tint`], mix(t[`bp-${k}`], t['bp-sf'], 0.1)), k).toBe(true);
    });
    it('edge tokens are the status colour at 35% (accent 60%) alpha', () => {
      const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(' ');
      for (const [k, a] of [['ok', '.35'], ['wn', '.35'], ['no', '.35'], ['mu', '.35'], ['ac', '.6']]) {
        expect(t[`bp-${k}-edge`].replace(/\s+/g, ' '), k).toBe(`rgb(${rgb(t[`bp-${k}`])} / ${a})`);
      }
    });
  });
}

describe('prefers-color-scheme fallback', () => {
  it('repeats every dark token with the same value', () => {
    const block = css.match(/@media \(prefers-color-scheme: dark\)\s*\{\s*html\[data-template="blueprint"\]:not\(\[data-theme\]\)\s*\{([^}]*)\}/);
    expect(block).not.toBeNull();
    const fb = vars(block[1]);
    const dark = themeVars('dark');
    for (const k of REQUIRED) expect(fb[`bp-${k}`], k).toBe(dark[`bp-${k}`]);
  });
});

describe('bridge (S1)', () => {
  const legacy = vars(legacyCss.match(/^:root\s*\{([^}]*)\}/m)[1]);
  const bridge = rules(css).find((r) => r.sel === 'html[data-template="blueprint"]' && /--card-bg/.test(r.body));
  it('re-points only variables that exist in index.css :root', () => {
    expect(bridge).toBeTruthy();
    for (const k of Object.keys(vars(bridge.body))) expect(legacy[k], `--${k}`).toBeTruthy();
  });
  it('covers the variables the code uses most', () => {
    const b = vars(bridge.body);
    for (const k of ['bg-color','card-bg','surface-2','border-color','text-color','text-muted','success','danger','warning','info']) expect(b[k], k).toMatch(/^var\(--bp-/);
  });
});

describe('structure rules', () => {
  it('no raw px in padding/margin/gap', () => {
    const bad = [...css.matchAll(/(?:padding|margin|gap|row-gap|column-gap)[\w-]*\s*:\s*([^;}]+)/g)].filter(([, v]) => /(?<![\w.-])[1-9]\d*(?:\.\d+)?px/.test(v));
    expect(bad.map((m) => m[0])).toEqual([]);
  });
  it('no colour literals after the token section', () => {
    const body = css.slice(css.search(/@media screen/));
    expect(body).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(body).not.toMatch(/\brgba?\(/);
  });
  it('!important only inside the NEUTRALISERS fence (plus the print reset)', () => {
    const [before, rest] = rawCss.split('/* ===== NEUTRALISERS ===== */');
    const [fence, after] = rest.split('/* ===== /NEUTRALISERS ===== */');
    const strip = (s) => s.replace(/@media print[\s\S]*$/, '');
    expect(strip(before + after)).not.toMatch(/!important/);
    const n = (fence.match(/\{[^{}]*\}/g) || []).length;
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(25);
    expect((fence.match(/\/\* N\d+ /g) || []).length).toBe(n); // one numbered "what it beats" comment per rule
  });
  it('every fenced rule names a file:line', () => {
    const fence = rawCss.split('/* ===== NEUTRALISERS ===== */')[1].split('/* ===== /NEUTRALISERS ===== */')[0];
    for (const c of fence.match(/\/\* N\d+ [\s\S]*?\*\//g)) expect(c, c).toMatch(/\w+\.jsx:\d+/);
  });
  it('all visual CSS is screen-only (top level = tokens, screen, print, tokens-only media)', () => {
    let depth = 0, cur = ''; const tops = [];
    for (const ch of css) {
      if (ch === '{') { if (!depth) tops.push(cur.trim()); depth++; cur = ''; }
      else if (ch === '}') { depth--; cur = ''; }
      else if (!depth) cur += ch;
    }
    const ok = (p) => p.startsWith('@media screen') || p.startsWith('@media print') || p.startsWith('@media (prefers-color-scheme') || p.startsWith('@media (max-width') || p.startsWith('html[data-template="blueprint"]');
    expect(tops.filter((p) => p && !ok(p))).toEqual([]);
  });
  it('top-level rules and token media blocks declare only custom properties (plus the print reset)', () => {
    const top = css.replace(/@media screen\s*\{[\s\S]*\n\}\s*(?=@media print)/, '').replace(/@media print\s*\{[\s\S]*$/, '');
    for (const [, body] of top.matchAll(/\{([^{}]*)\}/g)) {
      for (const decl of body.split(';').map((d) => d.trim()).filter(Boolean)) expect(decl, decl).toMatch(/^--/);
    }
  });
  it('print block only resets the grid background', () => {
    const p = css.match(/@media print\s*\{([\s\S]*)\}\s*$/)[1];
    expect(p.replace(/\s+/g, ' ').trim()).toBe('html[data-template="blueprint"] body { background-image: none !important; }');
  });
  it('size constants hold: tap 48, header 64/56, one 768 breakpoint', () => {
    const l = themeVars('light');
    expect(css).toMatch(/--bp-tap:\s*48px/);
    expect(css).toMatch(/--bp-hh:\s*64px/);
    expect(css).toMatch(/--bp-hh:\s*56px/);
    expect(css).toMatch(/\.bp-btn\s*\{[^}]*min-height:\s*var\(--bp-tap\)/);
    expect(css).toMatch(/\.bp-in\s*\{[^}]*min-height:\s*var\(--bp-tap\)/);
    const widths = [...css.matchAll(/max-width:\s*(\d+)px\)/g)].map((m) => m[1]).filter((w) => w !== '520' && w !== '384' && w !== '720');
    expect(new Set(widths)).toEqual(new Set(['768', '1023']));
    expect(l['bp-line-ui']).toBeTruthy();
  });
  it('reduced motion stops the pulsing dot', () => {
    expect(css).toMatch(/prefers-reduced-motion:\s*reduce\)\s*\{\s*\.bp-dot\s*\{\s*animation:\s*none/);
  });
});
