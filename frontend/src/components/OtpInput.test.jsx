import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import OtpInput from './OtpInput';

const base = { otp: '', setOtp: () => {}, onVerify: () => {}, onBack: () => {}, phoneNumber: '2567****22' };

describe('OtpInput', () => {
  it('keeps a pasted code that contains a space (no 6-char truncation of the raw text)', () => {
    const setOtp = vi.fn();
    render(<OtpInput {...base} setOtp={setOtp} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '123 456' } });
    expect(setOtp).toHaveBeenCalledWith('123456');
  });

  it('asks the phone keyboard to offer the SMS code', () => {
    render(<OtpInput {...base} />);
    expect(screen.getByRole('textbox')).toHaveAttribute('autocomplete', 'one-time-code');
  });

  it('shows the wrong-code message and tries left inline', () => {
    render(<OtpInput {...base} otp="123456" feedback={{ reason: 'wrong_code', message: 'That code is not correct. 2 tries left.' }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('2 tries left');
  });

  it('locks the field and shows a countdown when the server says guess_lock', () => {
    render(<OtpInput {...base} otp="123456" feedback={{ reason: 'guess_lock', lock_until: Date.now() + 90_000 }} />);
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(/try again in/i);
    expect(screen.getByRole('button', { name: /verify/i })).toBeDisabled();
  });
});
