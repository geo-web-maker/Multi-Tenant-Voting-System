import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), delete: vi.fn() }, getErrorMessage: (_e, d) => d }));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => async () => true }));

import InsightsCard from './InsightsCard';
import LinkBuilder from './LinkBuilder';
import AnalyticsPanel from './AnalyticsPanel';

describe('D2c: InsightsCard', () => {
  it('shows a calm empty message, never NaN', () => {
    render(<InsightsCard summary={{}} />);
    expect(screen.getByText(/Not enough activity/)).toBeTruthy();
    expect(screen.getByTestId('insights-card').textContent).not.toMatch(/NaN/);
  });
  it('lists the sentences', () => {
    render(<InsightsCard summary={{ funnels: { voting: { identity: { attempts: 10, failed: 5, reasons: [] } } } }} />);
    expect(screen.getByText('5 of 10 identity checks failed (50%).')).toBeTruthy();
  });
});

describe('D2c: LinkBuilder', () => {
  it('builds the link for the chosen channel and calls the copy handler with it', async () => {
    const onCopy = vi.fn();
    render(<LinkBuilder host="vote.example.org" onCopy={onCopy} />);
    expect(screen.getByLabelText('Tagged link').value).toBe('https://vote.example.org/?src=whatsapp');
    fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'poster-qr' } });
    fireEvent.click(screen.getByText('Copy link'));
    await waitFor(() => expect(onCopy).toHaveBeenCalledWith('https://vote.example.org/?src=poster-qr'));
  });
  it('rejects an invalid custom tag: error shown, no link, copy disabled', () => {
    const onCopy = vi.fn();
    render(<LinkBuilder host="vote.example.org" onCopy={onCopy} />);
    fireEvent.change(screen.getByLabelText('Channel'), { target: { value: '__custom__' } });
    fireEvent.change(screen.getByLabelText('Custom tag'), { target: { value: 'Bad Tag!' } });
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByLabelText('Tagged link').value).toBe('');
    expect(screen.getByText('Copy link').disabled).toBe(true);
    expect(onCopy).not.toHaveBeenCalled();
  });
  it('accepts a valid custom tag', () => {
    render(<LinkBuilder host="vote.example.org" onCopy={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Channel'), { target: { value: '__custom__' } });
    fireEvent.change(screen.getByLabelText('Custom tag'), { target: { value: 'hall-b' } });
    expect(screen.getByLabelText('Tagged link').value).toBe('https://vote.example.org/?src=hall-b');
  });
});

describe('D2c: mounted in the analytics tab', () => {
  beforeEach(() => mockGet.mockReset());
  it('shows both cards', async () => {
    mockGet.mockImplementation((url) => Promise.resolve({ data: url === '/superadmin/analytics/summary'
      ? { totals: {}, timeline: { points: [] }, funnels: {}, api: [], perf: [], network: [], hotspots: {}, meta: {} } : {} }));
    render(<AnalyticsPanel />);
    await waitFor(() => screen.getByTestId('insights-card'));
    expect(screen.getByTestId('link-builder')).toBeTruthy();
  });
});
