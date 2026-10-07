// BP-T9 · L8 ratchet + L5(a) static-import fence.
// The hex-literal count in screen code may only go DOWN. When you remove literals, lower HEX_CEILING.
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.dirname(fileURLToPath(import.meta.url));
const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const HEX_CEILING = 394; // recorded at the end of BP-T9
// Swept for the template: none of these literals may appear bare (outside var(--x, <literal>)).
const SWEPT_BARE = /(?<![0-9A-Za-z#])#(2ecc71|10b981|e74c3c|ef4444|e67e22|3498db|3b82f6)\b(?![0-9a-fA-F])/;
const SWEPT_FILES = ['SecurityPanel','ContactChangesQueue','ResetOtpLimitsPanel','VoterImportReview','VoterFieldsPanel',
  'ContactChangePanel','PaymentInfoPanel','UploadBypassPanel','ApplicantPortal','LinkBuilder','AnalyticsPanel',
  'ExportModeControl','VoterRegisterExport','BallotBox','AdminHeader','OtpInput','UIFeedback','Results',
  'ColumnMapper','VerifyCertificate','CommissionDashboard','OverseerDashboard','SuperAdminDashboard'];

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== 'node_modules') walk(p, out); } else out.push(p);
  }
  return out;
}
const rel = (p) => path.relative(SRC, p).split(path.sep).join('/');
const screenJsx = () => walk(SRC).filter((p) => p.endsWith('.jsx') && !/\.test\./.test(p) && !rel(p).startsWith('templates/blueprint/'));
const maskFallbacks = (s) => s.replace(/var\(--[a-z-]+,\s*#[0-9a-fA-F]{3,8}\)/g, 'var()');

describe('BP-T9 hex ratchet', () => {
  it('hex literals in non-test src/**/*.jsx (excluding templates/blueprint/) do not exceed the recorded ceiling', () => {
    let n = 0;
    for (const f of screenJsx()) n += (fs.readFileSync(f, 'utf8').match(HEX) || []).length;
    expect(n).toBeLessThanOrEqual(HEX_CEILING);
  });

  it('swept files carry the top hotspot literals only as var(--bp-x, <literal>) fallbacks', () => {
    const offenders = [];
    for (const f of screenJsx()) {
      const base = path.basename(f, '.jsx');
      if (!SWEPT_FILES.includes(base)) continue;
      maskFallbacks(fs.readFileSync(f, 'utf8')).split('\n').forEach((l, i) => {
        if (SWEPT_BARE.test(l)) offenders.push(`${rel(f)}:${i + 1}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it('no component outside templates/blueprint/ imports it statically (dynamic import() only)', () => {
    const bad = [];
    for (const f of walk(SRC).filter((p) => /\.(jsx?|mjs)$/.test(p) && !/\.test\./.test(p))) {
      if (rel(f).startsWith('templates/blueprint/')) continue;
      const s = fs.readFileSync(f, 'utf8');
      if (/^\s*(import|export)\s[^;]*?from\s+['"][^'"]*templates\/blueprint[^'"]*['"]/m.test(s)) bad.push(rel(f));
    }
    expect(bad).toEqual([]);
  });
});
