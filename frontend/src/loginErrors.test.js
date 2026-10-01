import { describe, it, expect } from 'vitest';
import { loginGuidance, cleanOtp } from './loginErrors';

describe('loginGuidance', () => {
  it.each([
    ['Student ID not found.', 'not_on_roll', /format 23\/U\/XXX\/00000\/GV/, 'check_register'],
    ['Name mismatch. Please provide your full registered names.', 'name_mismatch', /as they appear on the voter register/, 'check_register'],
    ['Already voted.', 'already_voted', /already voted/, undefined],
    ['No phone found.', 'no_phone', /contact change/i, 'contact_change'],
    ['SMS delivery failed.', 'sms_failed', /Wait a minute/, undefined],
  ])('%s', (detail, reason, text, action) => {
    for (const r of [reason, undefined]) {                       // by reason code AND by text alone
      const g = loginGuidance(detail, r);
      expect(g.message).toMatch(text);
      expect(g.action).toBe(action);
    }
  });
  it('passes unknown server text through unchanged', () => {
    expect(loginGuidance('Something new.', undefined)).toEqual({ title: 'Login Error', message: 'Something new.' });
  });
  it('never renders [object Object]', () => {
    expect(loginGuidance({ a: 1 }).message).toBe('{"a":1}');
    expect(loginGuidance(undefined).message).toBe('Verification Failed');
  });
});

describe('cleanOtp', () => {
  it('keeps a pasted code with spaces intact', () => { expect(cleanOtp('123 456')).toBe('123456'); });
  it('strips non-digits and caps at 6', () => { expect(cleanOtp('12-34a56789')).toBe('123456'); });
  it('handles empty', () => { expect(cleanOtp(undefined)).toBe(''); });
});
