import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DemoInbox from './DemoInbox';

const get = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => get(...a) } }));
vi.mock('./icons.jsx', () => ({ Icon: ({ name }) => <span data-icon={name} /> }));

describe('DemoInbox', () => {
  beforeEach(() => {
    get.mockReset();
    sessionStorage.clear();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it('renders nothing when the public inbox returns 404', async () => {
    get.mockRejectedValue({ response: { status: 404 } });
    const { container } = render(<DemoInbox />);
    await waitFor(() => expect(get).toHaveBeenCalledWith('/demo/inbox'));
    expect(container).toBeEmptyDOMElement();
  });

  it('shows OTP copy and status-link open actions while demo is active', async () => {
    get.mockResolvedValue({ data: { enabled: true, messages: [
      { id: '1', kind: 'otp', to: '256700000101', message: 'Your code is 123456.' , created_at: '2026-10-07T12:00:01Z' },
      { id: '2', kind: 'candidate_status_link', to: '256700000102', message: 'Check status: https://example.test/status/x', created_at: '2026-10-07T11:59:00Z' },
    ] } });
    render(<DemoInbox />);
    await screen.findByRole('button', { name: /Open demo message inbox/i });
    fireEvent.click(screen.getByRole('button', { name: /Open demo message inbox/i }));
    expect(screen.getByText(/Your code is 123456/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Copy code/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('123456');
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', 'https://example.test/status/x');
    expect(screen.getByText('DEMO: no real SMS sent')).toBeInTheDocument();
  });
});
