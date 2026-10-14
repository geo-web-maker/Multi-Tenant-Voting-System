import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(path, 'utf8');

describe('BK guide: Backups tab architecture and safety patterns', () => {
  const panel = read('src/components/BackupsPanel.jsx');
  const dash = read('src/components/SuperAdminDashboard.jsx');
  const components = [
    'BackupOverview.jsx', 'BackupConnections.jsx', 'BackupB2.jsx', 'BackupMirror.jsx',
    'BackupRestoreTest.jsx', 'BackupMigration.jsx', 'BackupSettings.jsx', 'BackupJobList.jsx',
  ];

  it('places Backups in Platform after Performance', () => {
    const performanceIndex = dash.indexOf("id: 'performance'");
    const backupsIndex = dash.indexOf("id: 'backups'");
    expect(performanceIndex).toBeGreaterThanOrEqual(0);
    expect(backupsIndex).toBeGreaterThan(performanceIndex);
    expect(dash).toContain("activeTab === 'backups'");
  });

  it('has the seven requested mobile sub-tabs and shared polling/reveal/loading conventions', () => {
    for (const title of ['Overview', 'Connections', 'Backblaze', 'Second DB', 'Staging (restore test)', 'Migration', 'Settings']) {
      expect(panel).toContain(title);
    }
    expect(panel).toContain('role="tablist"');
    expect(panel).toContain('usePolling(load, 60000, auto)');
    expect(panel).toContain('usePolling(loadJobs, 3000, auto && hasRunning)');
    expect(panel).toContain('<RevealGroup');
    expect(panel).toContain("getErrorMessage(e, 'Unable to load Backups.')");
  });

  it('splits all required areas and uses the existing Site Usage/Performance chart components', () => {
    for (const file of components) expect(read(`src/components/${file}`)).toBeTruthy();
    expect(read('src/components/BackupOverview.jsx')).toContain('PerfChart');
    expect(read('src/components/BackupOverview.jsx')).toContain('AlertPanel');
    expect(read('src/components/BackupB2.jsx')).toContain('BarRows');
  });

  it('wires read/write endpoints and marks keep-data as an environment-only value', () => {
    // Render free: the poll asks for /summary (which already carries connections, b2, mirror and migration), the
    // job list, and the extras a tab needs (stats on the overview tab, config once). It must not fan out to the
    // individual endpoints on every refresh.
    for (const path of ['/summary', '/stats', '/jobs', '/config']) {
      expect(panel).toContain(`\`${'${ROOT}'}${path}`);
    }
    for (const path of ['/connections`', '/b2`', '/mirror`', '/migration`']) {
      expect(panel).not.toContain(`\`${'${ROOT}'}${path}`);
    }
    expect(read('src/components/BackupSettings.jsx')).toContain('RESTORE_TEST_KEEP_DATA');
    expect(read('src/components/BackupSettings.jsx')).not.toContain("set('restore_test_keep_data'");
  });

  it('uses CSS tokens rather than literal hex colours in new backup UI components', () => {
    for (const file of ['BackupUI.jsx', ...components]) {
      expect(read(`src/components/${file}`)).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
  });
});
