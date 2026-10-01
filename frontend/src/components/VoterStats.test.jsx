import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a) } }));

import VoterStats from './VoterStats';

const DATA = {
  total: 120, voted: 30, not_voted: 90, turnout_pct: 25, with_phone: 100, without_phone: 20,
  sections: [{ key: 'hostel', label: 'Hostel', groups: [{ label: 'Block A', registered: 80, voted: 20, pct: 25 }] }],
  sms: { sent_total: 340, budget_total: 1000, budget_left: 660 },
};

describe('CUSTOM-1: VoterStats', () => {
  it('shows totals, per-section counts and the SMS amount', async () => {
    mockGet.mockResolvedValue({ data: DATA });
    render(<VoterStats />);
    await waitFor(() => expect(screen.getByTestId('voter-stats')).toBeTruthy());
    expect(mockGet).toHaveBeenCalledWith('/admin/voters/stats');
    const t = screen.getByTestId('voter-stats').textContent;
    expect(t).toContain('120'); expect(t).toContain('Voters by Hostel'); expect(t).toContain('Block A');
    expect(t).toContain('340'); expect(t).toContain('660 / 1000'); expect(t).not.toMatch(/NaN|undefined/);
  });
  it('says so when the numbers cannot load', async () => {
    mockGet.mockRejectedValue(new Error('x'));
    render(<VoterStats />);
    await waitFor(() => expect(screen.getByText(/Could not load voter statistics/)).toBeTruthy());
  });
});
