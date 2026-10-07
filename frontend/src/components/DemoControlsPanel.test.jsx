import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DemoControlsPanel from './DemoControlsPanel';

const get = vi.fn();
const post = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => get(...a), post: (...a) => post(...a) } }));
vi.mock('../template', () => ({ getTemplate: () => null }));

describe('DemoControlsPanel', () => {
  beforeEach(() => {
    get.mockReset(); post.mockReset();
    get.mockResolvedValue({ data: { enabled: false, counts: {}, credentials: {} } });
    post.mockResolvedValue({ data: { status: 'enabled', enabled: true, expires_at: '2026-10-10T12:00:00Z', counts: {}, credentials: {} } });
  });

  it('requires a reason and enables demo mode through the backend control', async () => {
    render(<DemoControlsPanel />);
    await screen.findByText('Disabled');
    fireEvent.change(screen.getByPlaceholderText(/Reason \(required\)/i), { target: { value: 'Client walkthrough' } });
    fireEvent.click(screen.getByRole('button', { name: 'Enable' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith('/superadmin/demo/enable', { reason: 'Client walkthrough', days: 3 }));
  });

  it('offers all five phase-jump controls when active', async () => {
    get.mockResolvedValue({ data: { enabled: true, expires_at: '2026-10-10T12:00:00Z', counts: {}, credentials: {} } });
    render(<DemoControlsPanel />);
    expect(await screen.findByRole('button', { name: 'applications' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'vetting' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'campaign' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'voting' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'results' })).toBeInTheDocument();
    expect(screen.getByText(/remaining/i)).toBeInTheDocument();
  });
});
