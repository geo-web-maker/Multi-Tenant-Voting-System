import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExportModeControl from './ExportModeControl';

describe('ExportModeControl', () => {
  it('shows three options and marks the current one', () => {
    render(<ExportModeControl name="A" mode="redacted" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Off' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Redacted' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Full' })).toHaveAttribute('aria-pressed', 'false');
  });
  it('calls onChange only when the mode differs', async () => {
    const onChange = vi.fn();
    render(<ExportModeControl name="A" mode="none" onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Off' }));
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Full' }));
    expect(onChange).toHaveBeenCalledWith('full');
  });
  it('is inert while saving', async () => {
    const onChange = vi.fn();
    render(<ExportModeControl name="A" mode="none" disabled onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Full' }));
    expect(onChange).not.toHaveBeenCalled();
  });
  it('active button text is white (dark-mode contrast)', () => {
    render(<ExportModeControl name="A" mode="full" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Full' }).style.color).toBe('rgb(255, 255, 255)');
  });
});
