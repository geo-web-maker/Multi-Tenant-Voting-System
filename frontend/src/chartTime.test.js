import { describe, it, expect } from 'vitest';
import { bucketLabel, defaultRangeDays } from './chartTime';

describe('D2a bucketLabel', () => {
  it('UTC 23:30 on day X shows as day X+1 00:30 in Africa/Kampala (hour bucket, instants on the hour)', () => {
    // 21:00Z is 00:00 the next day in EAT (UTC+3)
    expect(bucketLabel('2026-09-14T21:00:00Z', 'hour', 'Africa/Kampala')).toBe('15/9 00h');
    expect(bucketLabel('2026-09-14T23:00:00Z', 'hour', 'Africa/Kampala')).toBe('15/9 02h');
  });
  it('the same instant in UTC keeps day X', () => {
    expect(bucketLabel('2026-09-14T23:00:00Z', 'hour', 'UTC')).toBe('14/9 23h');
  });
  it('crosses a month boundary', () => {
    expect(bucketLabel('2026-09-30T22:00:00Z', 'hour', 'Africa/Kampala')).toBe('1/10 01h');
  });
  it('day buckets keep their plain UTC date', () => {
    expect(bucketLabel('2026-09-14', 'day', 'Africa/Kampala')).toBe('14/9');
    expect(bucketLabel('2026-09-14', 'day', 'America/Los_Angeles')).toBe('14/9');
  });
  it('bad input gives an empty label, never "NaN"', () => {
    expect(bucketLabel('', 'hour')).toBe('');
    expect(bucketLabel('nonsense', 'hour')).toBe('');
    expect(bucketLabel(undefined, 'day')).toBe('');
  });
});

describe('D2a defaultRangeDays', () => {
  const now = new Date('2026-10-01T10:00:00Z');
  it('Last 24 hours when all data started today', () => {
    expect(defaultRangeDays('2026-10-01', now)).toBe(1);
  });
  it('7 days when data started earlier', () => {
    expect(defaultRangeDays('2026-09-30', now)).toBe(7);
    expect(defaultRangeDays('2026-09-01', now)).toBe(7);
  });
  it('7 days when there is no data or a bad value', () => {
    expect(defaultRangeDays(null, now)).toBe(7);
    expect(defaultRangeDays(undefined, now)).toBe(7);
    expect(defaultRangeDays('x', now)).toBe(7);
  });
});
