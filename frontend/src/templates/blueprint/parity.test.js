import { describe, it, expect } from 'vitest';
import { css, mock } from './cssTools.js';
import { RENAME, TOOLING } from './rename.js';

describe('class parity with the mockup', () => {
  const style = mock.match(/<style>([\s\S]*?)<\/style>/)[1];
  const used = [...new Set([...style.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]))].filter((c) => !TOOLING.includes(c));
  it('every mockup class has its bp- twin in blueprint.css', () => {
    const missing = used.filter((c) => !new RegExp(`\\.${RENAME[c] ?? 'bp-' + c}(?![\\w-])`).test(css));
    expect(missing).toEqual([]);
  });
  it('the rename map points only at bp- names and never at tooling', () => {
    for (const [k, v] of Object.entries(RENAME)) { expect(v.startsWith('bp-'), k).toBe(true); }
    for (const c of TOOLING) expect(RENAME[c]).toBeUndefined();
  });
  it('tooling selectors are not shipped', () => {
    expect(css).not.toMatch(/\.(tb|gd|sp|sw)\b|\.dev\b|#st\b|#sc\b/);
  });
  it('no mockup color-mix() survives (precomputed tokens instead)', () => {
    expect(css).not.toMatch(/color-mix\(/);
  });
});
