import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), delete: vi.fn() }, getErrorMessage: (_e, d) => d }));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => async () => true }));

import AnalyticsPanel from './AnalyticsPanel';

const today = new Date().toISOString().slice(0, 10);
const serve = (since) => mockGet.mockImplementation((url) => Promise.resolve({ data: url === '/superadmin/analytics/summary'
  ? { totals: {}, tracking_since: since, timeline: { bucket: 'hour', points: [] }, funnels: {}, api: [], perf: [], network: [], meta: {} } : {} }));

describe('D2a default date range', () => {
  beforeEach(() => mockGet.mockReset());

  it('switches to Last 24 hours when all data started today', async () => {
    serve(today);
    render(<AnalyticsPanel />);
    await waitFor(() => expect(screen.getByLabelText('Date range').value).toBe('1'));
    const calls = mockGet.mock.calls.filter((c) => c[0] === '/superadmin/analytics/summary');
    expect(calls[calls.length - 1][1].params.days).toBe(1);
  });

  it('stays on 7 days when data started earlier', async () => {
    serve('2020-01-01');
    render(<AnalyticsPanel />);
    await waitFor(() => screen.getByText('Views and sessions'));
    expect(screen.getByLabelText('Date range').value).toBe('7');
  });

  it('does not override a range the user picked', async () => {
    serve(today);
    render(<AnalyticsPanel />);
    const select = await waitFor(() => screen.getByLabelText('Date range'));
    fireEvent.change(select, { target: { value: '30' } });
    await waitFor(() => screen.getByText('Views and sessions'));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByLabelText('Date range').value).toBe('30');
  });
});
