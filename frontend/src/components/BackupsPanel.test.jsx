import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();
const mockConfirm = vi.fn(async () => true);
const mockToast = vi.fn();

vi.mock('../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    put: (...args) => mockPut(...args),
    delete: (...args) => mockDelete(...args),
  },
  getErrorMessage: (_error, fallback) => fallback,
}));
vi.mock('../hooks/usePolling', () => ({ default: () => {} }));
vi.mock('./RevealGroup', () => ({
  default: ({ children }) => children,
  useRevealReady: () => {},
}));
vi.mock('./UIFeedback', () => ({
  useToast: () => mockToast,
  useConfirm: () => mockConfirm,
}));

import BackupsPanel from './BackupsPanel';

const ROOT = '/superadmin/backups';
const fixture = () => {
  const sum = {
    overall: 'warning', checked_at: '2026-10-12T00:00:00Z', alerts: [],
    connections: [], guards: [],
    b2: { tenants: [{ tenant: 'org-1', slug: 'Org One', age_minutes: null, bytes_gz: 0 }],
      totals: { routine_bytes: 0, safety_bytes: 0, milestone_bytes: 0, cap_bytes: 10000000000 },
      object_count: 0, last_failure: null, asset_failures: 0 },
    mirror: { enabled: false, last_ok_at: null, counts: [], consecutive_failures: 0 },
    restore: { last: null, running: null, next_scheduled: null },
    migration: { ready: false, freeze_active: false, freeze: { active: false }, checklist: [],
      source: { label: 'Live database', database: 'live' }, target: { label: 'Migration target', database: 'target' },
      role_swap_checklist: {} },
    jobs_running: [],
  };
  const data = {
    [`${ROOT}/summary`]: sum,
    [`${ROOT}/connections`]: { overall: 'warning', connections: [], guards: [] },
    [`${ROOT}/b2`]: sum.b2,
    [`${ROOT}/mirror`]: sum.mirror,
    [`${ROOT}/stats`]: { range: '24h', points: [] },
    [`${ROOT}/jobs`]: { jobs: [] },
    [`${ROOT}/migration`]: sum.migration,
    [`${ROOT}/config`]: { values: {
      full_backup_active_hours: 36, full_backup_idle_hours: 192, mirror_lag_active_minutes: 60,
      mirror_lag_idle_minutes: 2160, mirror_size_warn_bytes: 419430400, restore_test_warn_days: 10,
      probe_slow_ms: 500, b2_slow_ms: 2000, sampling_minutes: 15, restore_test_weekly: true,
    }, environment: { restore_test_keep_data: false } },
  };
  return { sum, data };
};

const serve = () => {
  const { data } = fixture();
  mockGet.mockImplementation((url) => {
    const key = String(url).split('?')[0];
    const value = data[key];
    return value === undefined ? Promise.resolve({ data: {} }) : Promise.resolve({ data: value });
  });
};

beforeEach(() => {
  mockGet.mockReset(); mockPost.mockReset(); mockPut.mockReset(); mockDelete.mockReset();
  mockConfirm.mockReset(); mockConfirm.mockResolvedValue(true); mockToast.mockReset();
  window.sessionStorage.removeItem('view_as');
});
afterEach(() => { cleanup(); window.sessionStorage.removeItem('view_as'); });

describe('BackupsPanel behaviour smoke tests', () => {
  it('loads the control room and renders each of the seven sub-tabs', async () => {
    serve();
    render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
    for (const name of ['Overview', 'Connections', 'Backblaze', 'Second DB', 'Staging (restore test)', 'Migration', 'Settings']) {
      expect(screen.getByRole('tab', { name })).toBeTruthy();
    }
    fireEvent.click(screen.getByRole('tab', { name: 'Connections' }));
    await screen.findByRole('heading', { name: 'Connection actions' });
    fireEvent.click(screen.getByRole('tab', { name: 'Backblaze' }));
    await screen.findByRole('heading', { name: 'Routine backups by organisation' });
    fireEvent.click(screen.getByRole('tab', { name: 'Second DB' }));
    await screen.findByRole('heading', { name: 'Mirror status' });
    fireEvent.click(screen.getByRole('tab', { name: 'Staging (restore test)' }));
    await screen.findByRole('heading', { name: 'Staging (restore test)' });
    fireEvent.click(screen.getByRole('tab', { name: 'Migration' }));
    await screen.findByRole('heading', { name: 'Cutover readiness' });
    fireEvent.click(screen.getByRole('tab', { name: 'Settings' }));
    await screen.findByRole('heading', { name: 'Alert thresholds' });
  });

  it('offers retry after the initial summary load fails', async () => {
    mockGet.mockRejectedValue(new Error('connection failed'));
    render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backups unavailable' });
    serve();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
  });

  it('keeps the backup action disabled in a read-only view-as session', async () => {
    window.sessionStorage.setItem('view_as', 'true');
    serve();
    render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
    fireEvent.click(screen.getByRole('tab', { name: 'Backblaze' }));
    const button = await screen.findByRole('button', { name: 'Back up now' });
    expect(button.disabled).toBe(true);
  });

  it('asks for confirmation before the health-check job writes to the second cluster', async () => {
    serve();
    mockPost.mockResolvedValue({ data: { run_id: 'test-job', status: 'queued' } });
    render(<BackupsPanel />);
    await screen.findByRole('heading', { name: 'Backup infrastructure' });
    fireEvent.click(screen.getByRole('button', { name: 'Run all checks' }));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
    expect(mockPost).toHaveBeenCalledWith(`${ROOT}/health-check`, {
      include_restore_test: false, override_election_guard: false,
    });
  });
});
