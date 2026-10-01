import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), put: (...a) => mockPost(...a), delete: (...a) => mockPost(...a) },
  getErrorMessage: (_e, d) => d,
}));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => async () => true }));

import AnalyticsPanel from './AnalyticsPanel';
import AlertPanel from './AlertPanel';

const summary = (extra) => ({ totals: {}, timeline: { points: [] }, funnels: {}, api: [], perf: [], network: [], hotspots: {}, meta: {}, ...extra });
const serve = (extra) => mockGet.mockImplementation((url) => (
  url === '/superadmin/analytics/summary' ? Promise.resolve({ data: summary(extra) }) : Promise.resolve({ data: {} })));

describe('D2d: alert panel', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });

  it('renders nothing when the backend sends no alerts field', () => {
    const { container } = render(<AlertPanel alerts={undefined} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows Healthy for an empty list', () => {
    render(<AlertPanel alerts={[]} />);
    expect(screen.getByText('Healthy')).toBeTruthy();
  });

  it('shows Warning for a warning alert with its numbers', () => {
    render(<AlertPanel alerts={[{ kind: '429', level: 'warning', metric: 'HTTP 429 responses per minute', value: 31, threshold: 30 }]} />);
    expect(screen.getAllByText('Warning').length).toBeGreaterThan(0);
    expect(screen.getByText(/HTTP 429 responses per minute is 31 \(threshold 30\)/)).toBeTruthy();
  });

  it('shows Critical when a critical alert is present', () => {
    render(<AlertPanel alerts={[{ kind: '5xx', level: 'critical', metric: 'Server 5xx responses per minute', value: 12, threshold: 10 }]} />);
    expect(screen.getAllByText('Critical').length).toBeGreaterThan(0);
  });

  it('is read-only: no buttons inside the panel and no write call when mounted in the analytics tab', async () => {
    serve({ alerts: [{ kind: '5xx', level: 'critical', metric: 'Server 5xx responses per minute', value: 12, threshold: 10 }] });
    render(<AnalyticsPanel />);
    const panel = await waitFor(() => screen.getByTestId('alert-panel'));
    expect(panel.querySelectorAll('button, input, form').length).toBe(0);
    expect(mockPost).not.toHaveBeenCalled();
  });
});
