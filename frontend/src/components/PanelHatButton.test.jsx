import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockGet = vi.fn();
const mockSwitch = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), post: vi.fn() }, ADMIN_TOKEN_KEY: 'admin_token' }));
vi.mock('../hatSwitch', () => ({ switchHat: (...a) => mockSwitch(...a) }));
vi.mock('./UIFeedback', () => ({ useToast: () => vi.fn() }));

import PanelHatButton from './PanelHatButton';

beforeEach(() => { mockGet.mockReset(); mockSwitch.mockReset(); });

describe('PanelHatButton', () => {
  it('shows nothing when the admin is not linked to the panel', async () => {
    mockGet.mockResolvedValue({ data: { panel_linked: false } });
    const { container } = render(<PanelHatButton />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/admin/panel-link'));
    expect(container.textContent).toBe('');
  });

  it('shows nothing if the check fails', async () => {
    mockGet.mockRejectedValue(new Error('403'));
    const { container } = render(<PanelHatButton />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('switches to the panel when linked, and reports the overseer pause to its parent', async () => {
    mockGet.mockResolvedValue({ data: { panel_linked: true, overseer_paused: true } });
    mockSwitch.mockResolvedValue();
    const onStatus = vi.fn();
    render(<PanelHatButton onStatus={onStatus} />);
    fireEvent.click(await screen.findByText('Switch to Vetting Panel'));
    await waitFor(() => expect(mockSwitch).toHaveBeenCalled());
    expect(onStatus).toHaveBeenCalledWith({ panel_linked: true, overseer_paused: true });
  });
});
