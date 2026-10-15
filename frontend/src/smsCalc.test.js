import { describe, it, expect } from 'vitest';
import {
  countParts, variableNames, unknownTokens, renderTemplate, insertAtCaret, breakdownLabel, costPerSms, ugx,
  toCount, balanceNumber, partsAffordable, systemTotals, normalizePct, splitLabel, shortfalls,
} from './smsCalc';

describe('countParts (same vectors as backend/tests/test_sms_bulk.py)', () => {
  it('empty text', () => expect(countParts('')).toEqual({ chars: 0, encoding: 'GSM-7', parts: 0, remaining: 160 }));
  it('exactly the single limit is one part, one over is two', () => {
    expect(countParts('a'.repeat(160)).parts).toBe(1);
    const over = countParts('a'.repeat(161));
    expect(over.parts).toBe(2);
    expect(over.remaining).toBe(2 * 153 - 161);
  });
  it('two full parts, then three', () => {
    expect(countParts('a'.repeat(306)).parts).toBe(2);
    expect(countParts('a'.repeat(307)).parts).toBe(3);
  });
  it('an extended GSM character counts twice', () => {
    expect(countParts('€').chars).toBe(2);
    expect(countParts(`${'a'.repeat(159)}€`).parts).toBe(2);
  });
  it('an emoji flips the whole message to UCS-2', () => {
    const c = countParts('hi 😀');
    expect(c).toMatchObject({ encoding: 'UCS-2', chars: 5, parts: 1 });
    expect(countParts(`${'a'.repeat(70)}😀`).parts).toBe(2);
  });
  it('a curly apostrophe flips encoding', () => expect(countParts('it\u2019s').encoding).toBe('UCS-2'));
  it('honours custom limits', () => {
    const lim = { single_limit: 10, multi_limit: 5 };
    expect(countParts('a'.repeat(10), lim).parts).toBe(1);
    expect(countParts('a'.repeat(11), lim).parts).toBe(3);
  });
});

describe('variables', () => {
  const known = variableNames(['hostel']);
  it('base set plus enabled fields, no duplicates', () => {
    expect(known).toEqual(['name', 'first_name', 'reg_no', 'hostel']);
    expect(variableNames(['name']).filter((k) => k === 'name')).toHaveLength(1);
  });
  it('flags unknown tokens once each', () => expect(unknownTokens('{name} {foo} {foo} {bar}', known)).toEqual(['foo', 'bar']));
  it('renders known, leaves unknown and stray braces', () => {
    expect(renderTemplate('Hi {first_name} {hostel}{x} {', { first_name: 'Jane', hostel: 'A' })).toBe('Hi Jane A{x} {');
  });
  it('a missing value renders empty', () => expect(renderTemplate('Hi {hostel}!', { hostel: '' })).toBe('Hi !'));
  it('inserts at the caret and replaces a selection', () => {
    expect(insertAtCaret('Hello ', '{name}', 6, 6)).toEqual({ text: 'Hello {name}', caret: 12 });
    expect(insertAtCaret('Hello XX!', '{name}', 6, 8)).toEqual({ text: 'Hello {name}!', caret: 12 });
  });
});

describe('cost helpers', () => {
  it('never reports 0 when the price is unset', () => {
    expect(costPerSms(2, null)).toBeNull();
    expect(costPerSms(2, '')).toBeNull();
    expect(costPerSms(2, 35)).toBe(70);
    expect(costPerSms(0, 0)).toBe(0);
  });
  it('formats the breakdown and money', () => {
    expect(breakdownLabel({ 1: 480, 2: 20 })).toBe('480 × 1 part, 20 × 2 parts');
    expect(ugx(null)).toBe('—');
    expect(ugx(1500)).toBe('UGX 1,500');
  });
});

describe('system message totals', () => {
  const tpl = [
    { key: 'otp', parts: 2, provider: 'egosms', cost_per_sms: 60 },
    { key: 'approved', parts: 2, provider: 'mambosms', cost_per_sms: 20 },
    { key: 'test', parts: 1, provider: 'mambosms', cost_per_sms: null },
  ];
  it('toCount accepts whole numbers only', () => {
    expect([toCount('12'), toCount(''), toCount('-3'), toCount('4.9'), toCount('abc'), toCount(undefined)]).toEqual([12, 0, 0, 4, 0, 0]);
  });
  it('multiplies by quantity and splits by provider', () => {
    const t = systemTotals(tpl, { otp: '100', approved: '10' });
    expect(t.count).toBe(110);
    expect(t.parts).toBe(220);
    expect(t.cost).toBe(6200);
    expect(t.byProvider.egosms).toEqual({ parts: 200, cost: 6000, unpriced: false });
    expect(t.byProvider.mambosms).toEqual({ parts: 20, cost: 200, unpriced: false });
    expect(t.rows.otp).toEqual({ n: 100, parts: 200, cost: 6000 });
  });
  it('an unpriced message that is used makes the total null, never a smaller number', () => {
    const t = systemTotals(tpl, { otp: '1', test: '1' });
    expect(t.cost).toBeNull();
    expect(t.unpriced).toBe(true);
    expect(t.byProvider.mambosms.unpriced).toBe(true);
  });
  it('an unpriced message nobody sends is ignored', () => {
    expect(systemTotals(tpl, { otp: '2' }).cost).toBe(120);
  });
  it('nothing typed is a zero total', () => {
    expect(systemTotals(tpl, {})).toMatchObject({ count: 0, parts: 0, cost: 0 });
    expect(systemTotals(null, {})).toMatchObject({ count: 0, cost: 0 });
  });
});

describe('balances', () => {
  it('balanceNumber reads provider strings', () => {
    expect([balanceNumber('12,500.50'), balanceNumber(300), balanceNumber(''), balanceNumber(null), balanceNumber('n/a')]).toEqual([12500.5, 300, null, null, null]);
  });
  it('partsAffordable floors and needs both numbers', () => {
    expect(partsAffordable('1,000', 30)).toBe(33);
    expect(partsAffordable('1000', null)).toBeNull();
    expect(partsAffordable(null, 30)).toBeNull();
    expect(partsAffordable('1000', 0)).toBeNull();
  });
});

describe('bulk provider split helpers', () => {
  it('normalizePct clamps to 0-100 and falls back on junk', () => {
    expect(normalizePct('30')).toBe(30);
    expect(normalizePct(150)).toBe(100);
    expect(normalizePct(-5)).toBe(0);
    expect(normalizePct('')).toBe(50);
    expect(normalizePct('abc')).toBe(50);
    expect(normalizePct('33.9')).toBe(33);
  });
  it('splitLabel shows both shares adding to 100', () => expect(splitLabel(30)).toBe('EgoSMS 30% · MamboSMS 70%'));
  it('shortfalls lists only providers whose balance is known and too low', () => {
    const by = { egosms: { total_cost: 1000 }, mambosms: { total_cost: 500 } };
    expect(shortfalls(by, { egosms: { balance: '900' }, mambosms: { balance: '5,000' } })).toEqual(['egosms']);
    expect(shortfalls(by, { egosms: { error: 'x' }, mambosms: {} })).toEqual([]);
    expect(shortfalls({ egosms: { total_cost: null } }, { egosms: { balance: '1' } })).toEqual([]);
    expect(shortfalls(undefined, {})).toEqual([]);
  });
});
