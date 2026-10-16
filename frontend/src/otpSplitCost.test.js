import { describe, it, expect } from 'vitest';
import { estimateOtpCost } from './otpSplitCost';

const price = { egosms: 30, mambosms: 20 };

describe('estimateOtpCost', () => {
  it('splits first codes 30:70 and sends every resend through EgoSMS', () => {
    const r = estimateOtpCost({ voters: 1000, resendsPerVoter: 0.5, firstEgoPct: 30, resendEgoPct: 100, costPerPart: price });
    expect(r.messages).toEqual({ egosms: 800, mambosms: 700 });   // 300 + 500 ; 700 + 0
    expect(r.total).toBe(800 * 30 + 700 * 20);
    expect(r.resends).toBe(500);
  });
  it('treats 100:0 as one provider only', () => {
    const r = estimateOtpCost({ voters: 100, resendsPerVoter: 0, firstEgoPct: 100, resendEgoPct: 0, costPerPart: { egosms: 25, mambosms: null } });
    expect(r.messages).toEqual({ egosms: 100, mambosms: 0 });
    expect(r.total).toBe(2500);          // unpriced MamboSMS carries nothing, so the total is still known
  });
  it('reports an unknown total when a used provider has no price', () => {
    const r = estimateOtpCost({ voters: 100, resendsPerVoter: 0, firstEgoPct: 50, resendEgoPct: 0, costPerPart: { egosms: 25, mambosms: null } });
    expect(r.total).toBeNull();
    expect(r.missing).toEqual(['mambosms']);
  });
  it('multiplies by parts and clamps nonsense percentages', () => {
    const r = estimateOtpCost({ voters: 10, resendsPerVoter: 0, parts: 2, firstEgoPct: 500, resendEgoPct: -5, costPerPart: price });
    expect(r.messages.egosms).toBe(20);
  });
});
