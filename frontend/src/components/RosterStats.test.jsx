// Regression: the migration removed the local `statCard` style, so every non-clickable tile threw a
// ReferenceError the moment the snapshot loaded. Unit tests of the dashboards mock this panel out.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a) }, getErrorMessage: (_e, d) => d }));

import { RosterStats } from './SharedAdminPanels';

afterEach(() => { cleanup(); mockGet.mockReset(); });

const overview = {
  total_registered: 120, voted: 45, turnout_pct: 38, with_phone_on_file: 100, candidates: 12,
  positions: 5, applications_pending: 3, student_changes_pending: 1, is_open: true, is_certified: false,
};

describe('RosterStats', () => {
  it('renders every tile once the snapshot loads (clickable and plain)', async () => {
    mockGet.mockResolvedValue({ data: overview });
    render(<RosterStats onRegisteredClick={() => {}} />);
    expect(await screen.findByText('Ballots cast')).toBeTruthy();
    expect(screen.getByText('Pending roster changes')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Registered voters/ })).toBeTruthy();
    expect(screen.getByText('Voting open')).toBeTruthy();
  });

  it('renders plain tiles when Registered voters is not clickable', async () => {
    mockGet.mockResolvedValue({ data: overview });
    render(<RosterStats />);
    expect(await screen.findByText('Registered voters')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Registered voters/ })).toBeNull();
  });
});
