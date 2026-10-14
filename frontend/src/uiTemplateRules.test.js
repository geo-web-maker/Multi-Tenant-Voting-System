// Guard rails from docs/UI_TEMPLATE_MANUAL.md. These are ratchets: they list today's known exceptions and fail on NEW ones,
// so a later session cannot quietly invent another card or button style. They do not judge how a page looks:
// that still needs a look in both templates (manual section 7).
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname);
const read = (p) => fs.readFileSync(path.join(SRC, p), 'utf8');
const components = () => fs.readdirSync(path.join(SRC, 'components')).filter((f) => /\.jsx$/.test(f) && !/test/.test(f)).map((f) => `components/${f}`);
const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? (e.name === 'node_modules' ? [] : walk(path.join(dir, e.name))) : [path.join(dir, e.name)]));

// Panels built on the shared kit (manual section 3). These must stay kit-only.
const KIT_PANELS = [
  'AlertPanel', 'FunnelPanels', 'DeletedApplicationsPanel', 'NominationFormPanel', 'DemoControlsPanel', 'PerformancePanel', 'PerformanceSettings', 'PerfStorage', 'PerfOrgs',
  'BackupsPanel', 'BackupJobProgress', 'BackupOverview', 'BackupConnections', 'BackupB2', 'BackupMirror', 'BackupRestoreTest', 'BackupMigration', 'BackupSettings',
].map((n) => `components/${n}.jsx`);

// Files that may use the Blueprint card/button classes: the voter/applicant flow (Tier A) and the public turnout block.
const BP_CARD_ALLOWED = ['App.jsx', 'components/ApplicantPortal.jsx', 'components/BallotBox.jsx', 'components/LoginErrorActions.jsx', 'components/TurnoutBreakdown.jsx', 'components/AlertPanel.jsx'];

// Files that still define their own inline button styles (legacy admin dialect). Migrating one to the kit means removing it here.
// A file NOT in this list that adds a `const ...Btn = {` fails: use perf-btn instead.
const LEGACY_BUTTON_FILES = [
  // Core voter/applicant flow: preserve the existing task-specific forms, OTP, and voting interaction surfaces.
  'App.jsx',
  'components/ApplicantPortal.jsx',
  'components/BallotBox.jsx',
  'components/LoginErrorActions.jsx',
  'components/OtpInput.jsx',
  // Standalone/public tools: status portal, mapping/export, and public result controls keep their own navigation and data-entry affordances.
  'components/CandidateStatusPortal.jsx',
  'components/ColumnMapper.jsx',
  'components/Results.jsx',
  'components/VoterRegisterSearch.jsx',
  'components/VoterList.jsx',
  'components/TabBar.jsx',
  // Demo/help/utility surfaces use compact links, icon actions, or floating/help launchers rather than admin action pills.
  'components/DemoInbox.jsx',
  'components/FloatingHelpMenu.jsx',
  'components/HelpPanel.jsx',
  'components/HelpTriggers.jsx',
  'components/MobileMoneyNumber.jsx',
  'components/PanelHatButton.jsx',
  'components/UIFeedback.jsx',
  // Two compact inline text-link actions intentionally remain link-like, not large primary/destructive action buttons.
  'components/ResetOtpLimitsPanel.jsx',
  'components/SharedAdminPanels.jsx',
];

describe('UI template rules (docs/UI_TEMPLATE_MANUAL.md)', () => {
  it('there is exactly one Blueprint stylesheet', () => {
    const found = walk(SRC).filter((p) => /blueprint[^/]*\.css$/.test(p)).map((p) => path.relative(SRC, p));
    expect(found).toEqual(['templates/blueprint/blueprint.css']);
  });

  it('kit panels use kit classes only: no template-specific card, no hard-coded colours, no inline button styles', () => {
    for (const f of KIT_PANELS) {
      const src = read(f);
      expect(src, f).not.toMatch(/cls\.card|k\?\.card|bp-card/);
      // a token with a hex fallback, var(--x, #hex), is fine; a bare hex is not
      expect(src.replace(/var\(--[a-z0-9-]+,\s*#[0-9a-fA-F]{3,8}\)/g, ''), f).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(src, f).not.toMatch(/^const [a-zA-Z]*([bB]tn|[bB]utton)[a-zA-Z]* *= *\{/m);
      expect(src, f).not.toMatch(/backgroundColor: ?'var\(--(success|danger|info)\)'/);
    }
  });

  it('only Tier A files use the Blueprint card class', () => {
    for (const f of [...components(), 'App.jsx']) {
      if (BP_CARD_ALLOWED.includes(f)) continue;
      expect(read(f), f).not.toMatch(/cls\.card|k\?\.card|bp\.cls\.btn|k\?\.btn/);
    }
  });

  it('no new file invents its own button styles', () => {
    const offenders = [...components(), 'App.jsx'].filter((f) => /^const [a-zA-Z]*([bB]tn|[bB]utton)[a-zA-Z]* *= *\{/m.test(read(f)) && !LEGACY_BUTTON_FILES.includes(f));
    expect(offenders).toEqual([]);
  });

  it('the legacy list has no stale entries (remove a file once it is migrated)', () => {
    const stale = LEGACY_BUTTON_FILES.filter((f) => !/^const [a-zA-Z]*([bB]tn|[bB]utton)[a-zA-Z]* *= *\{/m.test(read(f)));
    expect(stale).toEqual([]);
  });

  it('every perf-* class a component uses is defined in index.css', () => {
    const css = read('index.css');
    const used = new Set();
    for (const f of components()) {
      for (const cn of read(f).matchAll(/className=\{?["'`]([^"'`]*)["'`]/g)) for (const m of cn[1].matchAll(/\bperf-([a-z0-9-]+)/g)) used.add(m[1]);
    }
    const hooks = new Set(['pill', 'sink']); // class names that are test/CSS hooks only (styled inline)
    const missing = [...used].filter((c) => !hooks.has(c) && !css.includes(`.perf-${c}`));
    expect(missing).toEqual([]);
  });

  it('Blueprint rules for the kit are scoped, inside @media screen, and free of !important', () => {
    const css = read('templates/blueprint/blueprint.css');
    const a = css.indexOf('===== PANEL KIT');
    const b = css.indexOf('===== /PANEL KIT');
    expect(a).toBeGreaterThan(css.indexOf('@media screen'));
    expect(b).toBeGreaterThan(a);
    const block = css.slice(a, b);
    expect(block).not.toContain('!important');
    for (const line of block.split('\n')) if (/^\s*html?\[|^\s*\.perf-/.test(line) && line.includes('{')) expect(line).toContain('data-template="blueprint"');
  });
});
