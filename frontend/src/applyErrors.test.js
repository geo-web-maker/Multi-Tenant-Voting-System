import { describe, it, expect } from 'vitest';
import { mapApplyError, missingFields, missingMessage, imageBlockReason, stepLabel, fileKey } from './applyErrors';

const http = (status, detail) => ({ response: { status, data: { detail } } });

describe('B1: mapApplyError (table)', () => {
  const cases = [
    ['no response, online', {}, true, /Couldn't reach the server/],
    ['no response, offline', {}, false, /offline/i],
    ['timeout', { code: 'ECONNABORTED' }, true, /took too long/],
    ['cancelled', { code: 'ERR_CANCELED' }, true, /^Cancelled/],
    ['400 over 5 MB', http(400, 'Image must be under 5MB.'), true, /over 5 MB/],
    ['400 already applied', http(400, 'You have already applied.'), true, /already applied/],
    ['400 file type', http(400, 'Only JPEG, PNG, WEBP, or GIF images are allowed.'), true, /not supported/],
    ['400 name mismatch keeps server text', http(400, "The name entered doesn't match our records for this Student ID. Please enter your full registered name."), true, /doesn't match/],
    ['403 closed keeps server text', http(403, 'Applications are closed.'), true, /closed/],
    ['404', http(404, 'Your Student ID was not found on the voter register.'), true, /not found/],
    ['422 list', http(422, [{ msg: 'Field required' }]), true, /Field required/],
    ['429', http(429, 'x'), true, /Too many attempts/],
    ['502', http(502, 'Image upload failed. Please try again.'), true, /busy/],
    ['500', http(500, ''), true, /our side/],
  ];
  for (const [name, err, online, re] of cases) {
    it(name, () => expect(mapApplyError(err, { online })).toMatch(re));
  }
});

describe('B1: validation helpers', () => {
  it('lists every missing field in page order', () => {
    const list = missingFields({});
    expect(list.map(x => x.field)).toEqual(['student_id', 'full_name', 'position_id', 'manifesto', 'payment_method', 'payment_proof']);
    expect(missingMessage(list)).toContain('Student registration number');
    expect(missingMessage(list)).toContain('Payment receipt');
  });
  it('whitespace-only counts as missing; a complete form has none', () => {
    expect(missingFields({ student_id: '  ', full_name: 'A', position_id: 'p', manifesto: 'm', payment_method: 'x', payment_proof: {} }).map(x => x.field)).toEqual(['student_id']);
    expect(missingFields({ student_id: 's', full_name: 'A', position_id: 'p', manifesto: 'm', payment_method: 'x', payment_proof: {} })).toEqual([]);
  });
  it('phone is only required when the org asks for it, and needs at least 9 digits', () => {
    const ok = { student_id: 's', full_name: 'A', position_id: 'p', manifesto: 'm', payment_method: 'x', payment_proof: {} };
    expect(missingFields({ ...ok })).toEqual([]);
    expect(missingFields({ ...ok }, { phoneRequired: true }).map(x => x.field)).toEqual(['phone']);
    expect(missingFields({ ...ok, phone: '12 34' }, { phoneRequired: true }).map(x => x.field)).toEqual(['phone']);
    expect(missingFields({ ...ok, phone: '0772 123 456' }, { phoneRequired: true })).toEqual([]);
  });
  it('block reasons are fixed labels', () => {
    expect(imageBlockReason(null)).toBe('missing_field');
    expect(imageBlockReason({ type: 'application/pdf', size: 10, name: 'a.pdf' })).toBe('bad_file_type');
    expect(imageBlockReason({ type: 'image/png', size: 6 * 1048576, name: 'a.png' })).toBe('too_large');
  });
});

describe('B2: stepLabel / B3: fileKey', () => {
  it('four steps with a photo, three without', () => {
    expect(stepLabel(1, true)).toBe('Checking your details (1/4)');
    expect(stepLabel(2, true)).toBe('Uploading photo (2/4)');
    expect(stepLabel(4, true)).toBe('Submitting (4/4)');
    expect(stepLabel(2, false)).toBe('Uploading receipt (2/3)');
    expect(stepLabel(3, false)).toBe('Submitting (3/3)');
  });
  it('fileKey is stable for the same file', () => {
    const f = { name: 'a.jpg', size: 5, lastModified: 9 };
    expect(fileKey(f)).toBe(fileKey({ ...f }));
    expect(fileKey(f)).not.toBe(fileKey({ ...f, size: 6 }));
  });
});
