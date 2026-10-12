import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();
const mockConfirm = vi.fn(async () => true);
const mockToast = vi.fn();
const pollCalls = [];

vi.mock('../api', () => ({
  default: {
    get: (...a) => mockGet(...a), post: (...a) => mockPost(...a),
    put: (...a) => mockPut(...a), delete: (...a) => mockDelete(...a),
  },
  getErrorMessage: (_e, fallback) => fallback,
}));
vi.mock('../hooks/usePolling', () => ({ default: (fn, ms, enabled) => { pollCalls.push([ms, !!enabled]); } }));
vi.mock('./RevealGroup', () => ({ default: ({ children }) => children, useRevealReady: () => {} }));
vi.mock('./UIFeedback', () => ({ useToast: () => mockToast, useConfirm: () => mockConfirm }));

import BackupsPanel from './BackupsPanel';

const ROOT = '/superadmin/backups';
const CHECK_NAMES = ['No election open', 'Verified copy', 'Final pass', 'Chain Verify', 'Backups fresh', 'Mirror healthy', 'Restore test', 'Write freeze'];

const build = ({ ready = false, freeze = { active: false }, checklist = [], jobs = [], collections = [] } = {}) => {
  const migration = { ready, freeze_active: !!freeze.active, freeze, checklist, last_result: { collections },
    source: { label: 'Live database', database: 'live' }, target: { label: 'Migration target', database: 'target' },
    role_swap_checklist: {} };
  const sum = { overall: 'warning', checked_at: '2026-10-12T00:00:00Z', alerts: [], connections: [], guards: [],
    b2: { tenants: [], totals: {}, object_count: 0 }, mirror: { enabled: false, counts: [] },
    restore: { last: null, running: null }, migration, jobs_running: [] };
  const data = {
    [`${ROOT}/summary`]: sum, [`${ROOT}/connections`]: { connections: [], guards: [] }, [`${ROOT}/b2`]: sum.b2,
    [`${ROOT}/mirror`]: sum.mirror, [`${ROOT}/stats`]: { points: [] }, [`${ROOT}/jobs`]: { jobs },
    [`${ROOT}/migration`]: migration, [`${ROOT}/config`]: { values: {}, environment: {} },
  };
  mockGet.mockImplementation((url) => Promise.resolve({ data: data[String(url).split('?')[0]] ?? {} }));
};

const openMigration = async () => {
  render(<BackupsPanel />);
  await screen.findByRole('heading', { name: 'Backup infrastructure' });
  fireEvent.click(screen.getByRole('tab', { name: 'Migration' }));
  await screen.findByRole('heading', { name: 'Cutover readiness' });
};

beforeEach(() => {
  [mockGet, mockPost, mockPut, mockDelete, mockToast].forEach((m) => m.mockReset());
  mockConfirm.mockReset(); mockConfirm.mockResolvedValue(true);
  pollCalls.length = 0; window.sessionStorage.removeItem('view_as');
});
afterEach(() => { cleanup(); window.sessionStorage.removeItem('view_as'); });

describe('Migration sub-tab behaviour', () => {
  it('shows "Not ready" when the summary says not ready, and "Ready to cut over" when ready', async () => {
    build({ ready: false }); await openMigration();
    expect(screen.getByText('Not ready to cut over')).toBeTruthy();
    cleanup(); build({ ready: true }); await openMigration();
    expect(screen.getByText('Ready to cut over')).toBeTruthy();
  });

  it.each(CHECK_NAMES)('marks a failing readiness condition as Blocked: %s', async (name) => {
    build({ ready: false, checklist: CHECK_NAMES.map((n) => ({ name: n, ok: n !== name })) });
    await openMigration();
    expect(screen.getAllByText('Blocked')).toHaveLength(1);
    expect(screen.getByText('Not ready to cut over')).toBeTruthy();
  });

  it('keeps Final pass disabled unless the freeze is active', async () => {
    build({ freeze: { active: false } }); await openMigration();
    expect(screen.getByRole('button', { name: 'Final pass' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Lift freeze' }).disabled).toBe(true);
    cleanup(); build({ freeze: { active: true, expires_in_seconds: 600, started_at: '2026-10-12T00:00:00Z' } });
    await openMigration();
    expect(screen.getByRole('button', { name: 'Final pass' }).disabled).toBe(false);
  });

  it('asks for confirmation before the final pass and posts nothing if declined', async () => {
    build({ freeze: { active: true, expires_in_seconds: 600 } }); await openMigration();
    mockConfirm.mockResolvedValueOnce(false);
    fireEvent.click(screen.getByRole('button', { name: 'Final pass' }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('disables every migration action in a view-as session', async () => {
    window.sessionStorage.setItem('view_as', 'true');
    build({ freeze: { active: true } }); await openMigration();
    for (const name of ['Plan (dry run)', 'Copy (rehearsal)', 'Lift freeze', 'Final pass', 'Verify migration']) {
      expect(screen.getByRole('button', { name }).disabled).toBe(true);
    }
  });

  it('caps the per-collection list at eight rows and expands on request', async () => {
    const collections = Array.from({ length: 12 }, (_, i) => ({ collection: `coll_${i}`, source: 10, target: 10, verified: true }));
    build({ collections }); await openMigration();
    expect(screen.queryByText('coll_11')).toBeNull();
    const more = screen.getAllByRole('button').find((b) => /show|more|all/i.test(b.textContent || ''));
    expect(more).toBeTruthy();
    fireEvent.click(more);
    expect(screen.getByText('coll_11')).toBeTruthy();
  });
});

describe('Polling lifecycle', () => {
  it('polls the summary every 30 s and the job list every 3 s only while a job runs', async () => {
    build({ jobs: [{ run_id: 'r1', kind: 'migration_copy', status: 'running', started_at: '2026-10-12T00:00:00Z' }] });
    render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
    expect(pollCalls).toContainEqual([30000, true]);
    expect(pollCalls).toContainEqual([3000, true]);
  });

  it('does not run the fast job poll when nothing is running', async () => {
    build({ jobs: [{ run_id: 'r1', kind: 'migration_copy', status: 'passed' }] });
    render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
    expect(pollCalls.filter(([ms]) => ms === 3000).every(([, on]) => on === false)).toBe(true);
  });

  it('turns polling off when auto-refresh is unticked', async () => {
    build(); render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
    pollCalls.length = 0;
    fireEvent.click(screen.getByLabelText(/Auto-refresh/));
    await waitFor(() => expect(pollCalls).toContainEqual([30000, false]));
  });
});
