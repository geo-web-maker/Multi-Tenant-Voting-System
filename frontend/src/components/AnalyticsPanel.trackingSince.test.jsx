import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), delete: vi.fn() }, getErrorMessage: (_e, d) => d }));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => async () => true }));

import AnalyticsPanel from './AnalyticsPanel';

const summary = (extra) => ({ totals: {}, timeline: { points: [] }, funnels: {}, api: [], perf: [], network: [], hotspots: {}, meta: {}, ...extra });
const serve = (extra) => mockGet.mockImplementation((url) => (
  url === '/superadmin/analytics/summary' ? Promise.resolve({ data: summary(extra) }) : Promise.resolve({ data: {} })));

describe('D2e: tracking-since line', () => {
  beforeEach(() => mockGet.mockReset());

  it('shows the date when tracking_since is set', async () => {
    serve({ tracking_since: '2026-09-14' });
    render(<AnalyticsPanel />);
    await waitFor(() => screen.getByText(/Tracking of funnel steps started on/));
    expect(screen.getByText(/started on 14 Sept?\.? 2026/)).toBeTruthy();
  });

  it('is hidden when tracking_since is null', async () => {
    serve({ tracking_since: null });
    render(<AnalyticsPanel />);
    await waitFor(() => screen.getByText('Views and sessions'));
    expect(screen.queryByText(/Tracking of funnel steps started on/)).toBeNull();
  });

  it('is hidden when the field is missing', async () => {
    serve({});
    render(<AnalyticsPanel />);
    await waitFor(() => screen.getByText('Views and sessions'));
    expect(screen.queryByText(/Tracking of funnel steps/)).toBeNull();
  });
});
