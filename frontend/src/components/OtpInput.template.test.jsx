import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import OtpInput from './OtpInput';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

afterEach(restoreTemplate);
const base = { otp: '', setOtp: () => {}, onVerify: () => {}, onBack: () => {}, phoneNumber: '2567****22' };

describe('OtpInput template seam', () => {
  it('default render has no bp- class', () => {
    useDefault();
    const { container } = render(<OtpInput {...base} />);
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
  });

  it('blueprint: still exactly ONE input, with the SMS-autofill attributes', async () => {
    await useBlueprint();
    const { container } = render(<OtpInput {...base} />);
    expect(container.querySelectorAll('input')).toHaveLength(1);
    const input = screen.getByRole('textbox');
    expect(input).toHaveAttribute('autocomplete', 'one-time-code');
    expect(input).toHaveAttribute('inputmode', 'numeric');
    expect(input).not.toHaveAttribute('maxlength');
    expect(container.querySelectorAll('.bp-otp i')).toHaveLength(6);
    expect(container.querySelector('.bp-otp i')).toHaveAttribute('aria-hidden', 'true');
    expect(input).toHaveAccessibleName(/confirm the code sent to/i);
  });

  it('blueprint: pasting "123 456" gives 123456, cells show the digits', async () => {
    await useBlueprint();
    const setOtp = vi.fn();
    const { container, rerender } = render(<OtpInput {...base} setOtp={setOtp} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '123 456' } });
    expect(setOtp).toHaveBeenCalledWith('123456');
    rerender(<OtpInput {...base} setOtp={setOtp} otp="123456" />);
    expect([...container.querySelectorAll('.bp-otp i')].map((i) => i.textContent).join('')).toBe('123456');
  });

  it('blueprint: disabled under 6 digits / submitting; enabled at 6; data-track kept', async () => {
    await useBlueprint();
    const { rerender } = render(<OtpInput {...base} otp="123" />);
    expect(screen.getByRole('button', { name: /verify/i })).toBeDisabled();
    rerender(<OtpInput {...base} otp="123456" />);
    const btn = screen.getByRole('button', { name: /verify/i });
    expect(btn).toBeEnabled();
    expect(btn).toHaveAttribute('data-track', 'otp-submit');
    rerender(<OtpInput {...base} otp="123456" isSubmitting />);
    expect(screen.getByRole('button', { name: 'Verifying…' })).toBeDisabled();
  });

  it('blueprint: wrong code -> one role=alert and error cells; lock -> countdown alert, input disabled', async () => {
    await useBlueprint();
    const { container, rerender } = render(<OtpInput {...base} otp="123456" feedback={{ reason: 'wrong_code', message: 'That code is not correct. 2 tries left.' }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('2 tries left');
    expect(container.querySelector('.bp-otp')).toHaveClass('bp-err');
    rerender(<OtpInput {...base} otp="123456" feedback={{ reason: 'guess_lock', lock_until: Date.now() + 90_000 }} />);
    expect(screen.getByRole('alert')).toHaveTextContent(/try again in/i);
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(container.querySelector('.bp-otp')).toHaveClass('bp-lock');
  });

  it('blueprint: Back calls onBack', async () => {
    await useBlueprint();
    const onBack = vi.fn();
    render(<OtpInput {...base} onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
