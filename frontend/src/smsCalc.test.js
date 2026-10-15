import { describe, it, expect } from 'vitest';
import {
  countParts, variableNames, unknownTokens, renderTemplate, insertAtCaret, breakdownLabel, costPerSms, ugx,
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
