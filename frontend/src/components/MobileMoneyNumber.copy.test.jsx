import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MobileMoneyNumber from './MobileMoneyNumber';

const info = { number: '256700123456', name: 'Test Treasurer' };

afterEach(() => { vi.restoreAllMocks(); });

describe('F1 MobileMoneyNumber tap-to-copy', () => {
  it('copies via the clipboard API and is labelled for analytics', async () => {
    const writeText = vi.fn().mockResolvedValue();
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<MobileMoneyNumber info={info} />);
    const btn = screen.getByRole('button', { name: /copy payment number/i });
    expect(btn.getAttribute('data-track')).toBe('apply-copy-number');
    expect(btn.style.minHeight).toBe('44px');
    fireEvent.click(btn);
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('Copied')).toBeTruthy());
  });

  it('falls back to execCommand when the clipboard API rejects', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('blocked')) }, configurable: true });
    document.execCommand = vi.fn().mockReturnValue(true);
    render(<MobileMoneyNumber info={info} />);
    fireEvent.click(screen.getByRole('button', { name: /copy payment number/i }));
    await waitFor(() => expect(document.execCommand).toHaveBeenCalledWith('copy'));
    await waitFor(() => expect(screen.getByText('Copied')).toBeTruthy());
  });

  it('renders nothing when no number is set', () => {
    const { container } = render(<MobileMoneyNumber info={{}} />);
    expect(container.innerHTML).toBe('');
  });
});
