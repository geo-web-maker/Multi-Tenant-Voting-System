import { describe, it, expect } from 'vitest';
import { ratio, legacyCss as css } from './templates/blueprint/cssTools.js';

// Every toast fill ships with its own ink (--toast-*-bg / -fg). Both themes must stay readable.
const block = (sel) => {
  const i = css.indexOf(`${sel} {`);
  return css.slice(i, css.indexOf('}', i));
};
const get = (b, name) => b.match(new RegExp(`--toast-${name}:\\s*(#[0-9a-f]{6})`, 'i'))[1];

for (const theme of ['light', 'dark']) {
  describe(`toast contrast (${theme})`, () => {
    const b = block(`[data-theme="${theme}"]`);
    it.each(['info', 'ok', 'err'])('%s ink on fill >= 4.5', (k) => {
      expect(ratio(get(b, `${k}-fg`), get(b, `${k}-bg`))).toBeGreaterThanOrEqual(4.5);
    });
  });
}
