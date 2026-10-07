import { describe, it, expect } from 'vitest';
import { themeVars, ratio } from './cssTools.js';

for (const theme of ['light', 'dark']) {
  describe(`contrast (${theme})`, () => {
    const t = Object.fromEntries(Object.entries(themeVars(theme)).map(([k, v]) => [k.replace('bp-', ''), v]));
    const TEXT = [['tx','sf'],['tx','bg'],['mu','sf'],['mu','bg'],['mu','sf2'],['mu','sf3'],['ai','ac'],['ac','sf'],['ac','sf2'],['ac','sf3'],
      ['ok','ok-tint'],['wn','wn-tint'],['no','no-tint'],['mu','mu-tint'],['ok','sf'],['wn','sf'],['no','sf'],['tx','tint'],['tx','tint2'],['ai','no'],['ai','ok'],['ai','wn']];   // ai on ok/wn/no: solid status fills (election buttons) use ink-on-fill
    it.each(TEXT)('text %s on %s >= 4.5', (fg, bg) => { expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5); });
    it.each(['sf', 'sf2', 'sf3'])('control boundary line-ui on %s >= 3 (D2)', (s) => { expect(ratio(t['line-ui'], t[s])).toBeGreaterThanOrEqual(3); });
    it('D3: accent text is only safe on card surfaces (light page bg / tint are known sub-4.5, so nobody "fixes" them silently)', () => {
      if (theme === 'light') { expect(ratio(t.ac, t.bg)).toBeLessThan(4.5); expect(ratio(t.ac, t.tint)).toBeLessThan(4.5); }
      else { expect(ratio(t.ac, t.bg)).toBeGreaterThanOrEqual(4.5); }
    });
    it('the mockup divider colour would fail the 3:1 control rule (why line-ui exists)', () => {
      expect(ratio(t.line, t.sf)).toBeLessThan(3);
    });
  });
}
