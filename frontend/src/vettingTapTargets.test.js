// E15: the Vetting Panel's action buttons reach the 44 px floor in Blueprint only.
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => fs.readFileSync(path.join(SRC, p), 'utf8');

describe('E15 vetting action targets', () => {
  it('blueprint.css lifts .vp-actions buttons and .vp-switch to 44px, scoped to the template', () => {
    const css = read('templates/blueprint/blueprint.css');
    expect(css).toMatch(/html\[data-template="blueprint"\] \.vp-actions button,\s*html\[data-template="blueprint"\] button\.vp-switch\s*\{[^}]*min-height:\s*44px/);
    expect(css.match(/\.vp-(actions|switch)[^{]*\{[^}]*!important/g)).toBeNull();
  });

  it('every vetting action row and switch button carries the class', () => {
    const vet = read('components/VettingDashboard.jsx');
    expect(vet.match(/className="vp-actions" style=\{row\}/g)).toHaveLength(4);
    expect(vet).toContain('className="vp-switch"');
    expect(read('components/PanelHatButton.jsx')).toContain('className="vp-switch"');
    expect(read('components/CommissionDashboard.jsx')).toContain('className="vp-switch"');
  });

  it('the classes do not start with bp- (default JS must carry no bp- strings)', () => {
    for (const f of ['VettingDashboard', 'PanelHatButton', 'CommissionDashboard']) {
      expect(read(`components/${f}.jsx`)).not.toMatch(/className="bp-(actions|switch)/);
    }
  });
});
