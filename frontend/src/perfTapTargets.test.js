// E17: the Performance tab reaches the 44 px / 48 px floors in Blueprint only, with plain class names.
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => fs.readFileSync(path.join(SRC, p), 'utf8');

describe('E17 performance tab targets', () => {
  it('blueprint.css lifts buttons to 44px and fields to 48px, scoped, without !important', () => {
    const css = read('templates/blueprint/blueprint.css');
    expect(css).toMatch(/html\[data-template="blueprint"\] \.perf-btn,\s*html\[data-template="blueprint"\] \.perf-actions button\s*\{[^}]*min-height:\s*44px/);
    expect(css).toMatch(/html\[data-template="blueprint"\] \.perf-field\s*\{[^}]*min-height:\s*48px/);
    expect(css.match(/\.perf-[^{]*\{[^}]*!important/g)).toBeNull();
  });
  it('the rule sits inside the screen-only block', () => {
    const css = read('templates/blueprint/blueprint.css');
    const at = css.indexOf('.perf-btn');
    const before = css.slice(0, at);
    expect(before.lastIndexOf('@media screen')).toBeGreaterThan(before.lastIndexOf('@media print'));
  });
  it('components carry the classes and none starts with bp-', () => {
    const panel = read('components/PerformancePanel.jsx');
    const settings = read('components/PerformanceSettings.jsx');
    expect(panel).toContain('className="perf-btn"');
    expect(settings).toContain('perf-field');
    expect(settings).toContain('perf-actions');
    for (const src of [panel, settings]) expect(src).not.toMatch(/className="bp-/);
  });
  it('uses no hex literals and no new chart library', () => {
    for (const f of ['components/PerformancePanel.jsx', 'components/PerformanceSettings.jsx', 'perfFormat.js']) {
      expect(read(f)).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
    expect(read('components/PerformancePanel.jsx')).not.toMatch(/chart\.js|react-chartjs|recharts/);
  });
  it('the tab is in the Platform group after Site Usage, behind the superadmin dashboard', () => {
    const dash = read('components/SuperAdminDashboard.jsx');
    expect(dash.indexOf("id: 'usage_analytics'")).toBeLessThan(dash.indexOf("id: 'performance'"));
    expect(dash).toContain("activeTab === 'performance' && <PerformancePanel />");
  });
});
