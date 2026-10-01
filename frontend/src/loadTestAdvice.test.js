import { describe, it, expect } from 'vitest';
import { loadTestAdvice, busiestHourShare } from './loadTestAdvice';

describe('D2b loadTestAdvice', () => {
  it('guide example: 1500 voters, 40% in the busiest hour, 180 s sessions -> 30', () => {
    expect(loadTestAdvice({ voters: 1500, shareBusiestHour: 0.40, avgSessionSeconds: 180 }).expected).toBe(30);
  });
  it('1.5x to 2x gives 45 to 60', () => {
    const r = loadTestAdvice({ voters: 1500, shareBusiestHour: 0.40, avgSessionSeconds: 180 });
    expect([r.low, r.high]).toEqual([45, 60]);
  });
  it('missing, zero, negative or non-numeric inputs give zeros, never NaN', () => {
    for (const bad of [{}, { voters: 0 }, { voters: -5, shareBusiestHour: 0.4, avgSessionSeconds: 100 }, { voters: 'x', shareBusiestHour: 'y', avgSessionSeconds: null }]) {
      expect(loadTestAdvice(bad)).toEqual({ expected: 0, low: 0, high: 0 });
    }
  });
  it('caps the busiest-hour share at 100%', () => {
    expect(loadTestAdvice({ voters: 100, shareBusiestHour: 5, avgSessionSeconds: 3600 }).expected).toBe(100);
  });
});

describe('D2b busiestHourShare', () => {
  it('is the busiest hour over the total', () => {
    const h = new Array(24).fill(0); h[10] = 40; h[11] = 60;
    expect(busiestHourShare(h)).toBeCloseTo(0.6);
  });
  it('is 0 for empty or missing data', () => {
    expect(busiestHourShare(new Array(24).fill(0))).toBe(0);
    expect(busiestHourShare(undefined)).toBe(0);
  });
});
