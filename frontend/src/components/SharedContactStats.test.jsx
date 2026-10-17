// The shared-number statistics live on the IT admin overview, in the same tiles as the roster snapshot.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a) }, getErrorMessage: (_e, d) => d }));

import { SharedContactStats } from './SharedAdminPanels';

afterEach(() => { cleanup(); mockGet.mockReset(); });

const stats = {
  shared_numbers: 4, unresolved_numbers: 3, accepted_numbers: 1, voters_sharing: 9, voters_sharing_pct: 2.5,
  possible_duplicates: 1, largest_group: 3, already_voted_sharing: 2, admin_role_sharing: 0,
};

describe('SharedContactStats', () => {
  it('shows every statistic and opens the fix panel from the Unresolved tile', async () => {
    mockGet.mockResolvedValue({ data: { groups: [], stats } });
    const onOpen = vi.fn();
    render(<SharedContactStats onOpen={onOpen} />);
    expect(await screen.findByText('Accepted as shared')).toBeTruthy();
    expect(screen.getByText('9 (2.5%)')).toBeTruthy();
    expect(screen.getByText('3 to resolve')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Unresolved/ }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledWith('/admin/shared-contacts');
  });

  it('says nothing is unresolved when there are no shared numbers', async () => {
    mockGet.mockResolvedValue({ data: { groups: [], stats: { ...stats, shared_numbers: 0, unresolved_numbers: 0 } } });
    render(<SharedContactStats />);
    expect(await screen.findByText('None unresolved')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Unresolved/ })).toBeNull();
  });
});
