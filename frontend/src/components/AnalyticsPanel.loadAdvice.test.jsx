import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), delete: vi.fn() }, getErrorMessage: (_e, d) => d }));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => async () => true }));

import AnalyticsPanel from './AnalyticsPanel';

const hours = new Array(24).fill(0); hours[9] = 60; hours[10] = 40;
mockGet.mockImplementation((url) => Promise.resolve({ data: url === '/superadmin/analytics/summary'
  ? { totals: { average_session_seconds: 180 }, hour_of_day: hours, timeline: { points: [] }, funnels: {}, api: [], perf: [], network: [], meta: {} } : {} }));

describe('D2b load-test advice in the panel', () => {
  beforeEach(() => mockGet.mockClear());
  it('shows nothing until a voter count is typed, then the planning range', async () => {
    render(<AnalyticsPanel />);
    const input = await waitFor(() => screen.getByLabelText('Eligible voters'));
    expect(screen.queryByText(/Expected people online at once/)).toBeNull();
    fireEvent.change(input, { target: { value: '1500' } });   // 1500 x 0.60 x 180/3600 = 45
    expect(screen.getByText(/about 45\./)).toBeTruthy();
    expect(screen.getByText(/Test with 68 to 90 users/)).toBeTruthy();
  });
});
