import { describe, it, expect } from 'vitest';
import { buildTaggedLink, CHANNELS, TAG_RE } from './linkBuilder';

describe('D2c: tagged-link builder', () => {
  it.each(['whatsapp', 'facebook', 'class-group', 'poster-qr', 'sms'])('%s builds https://<host>/?src=<tag>', (ch) => {
    expect(buildTaggedLink('vote.example.org', ch)).toEqual({ ok: true, url: `https://vote.example.org/?src=${ch}` });
  });
  it('covers exactly the five channels', () => {
    expect(CHANNELS).toEqual(['whatsapp', 'facebook', 'class-group', 'poster-qr', 'sms']);
  });
  it('accepts a valid custom tag and tidies the host', () => {
    expect(buildTaggedLink('https://vote.example.org/', 'hall_b-2026').url).toBe('https://vote.example.org/?src=hall_b-2026');
  });
  it.each(['', 'a', 'UPPER', 'has space', 'semi;colon', 'x'.repeat(41), 'a/b', 'ü-tag', null, undefined])('rejects invalid tag %j', (t) => {
    const r = buildTaggedLink('vote.example.org', t);
    expect(r.ok).toBe(false);
    expect(r.url).toBeUndefined();
  });
  it('rejects a missing or malformed host', () => {
    expect(buildTaggedLink('', 'sms').ok).toBe(false);
    expect(buildTaggedLink('a b.com', 'sms').ok).toBe(false);
  });
  it('tag rule matches the documented pattern bounds', () => {
    expect(TAG_RE.test('ab')).toBe(true);
    expect(TAG_RE.test('x'.repeat(40))).toBe(true);
  });
});
