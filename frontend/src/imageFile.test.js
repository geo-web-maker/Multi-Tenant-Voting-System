import { describe, it, expect } from 'vitest';
import { validateImageFile, snapshotFile, MAX_IMAGE_BYTES } from './imageFile';

const f = (name, type, size = 1000) => ({ name, type, size });

describe('validateImageFile', () => {
  it('accepts the four formats the server accepts', () => {
    for (const t of ['image/jpeg', 'image/png', 'image/webp', 'image/gif']) expect(validateImageFile(f('a', t))).toBe('');
  });
  it('rejects PDFs and HEIC, which the picker used to offer but the server refuses', () => {
    expect(validateImageFile(f('r.pdf', 'application/pdf'))).toMatch(/not supported/);
    expect(validateImageFile(f('p.heic', 'image/heic'))).toMatch(/not supported/);
  });
  it('rejects files over 5 MB with the size in the message', () => {
    expect(validateImageFile(f('big.jpg', 'image/jpeg', MAX_IMAGE_BYTES + 1))).toMatch(/limit is 5 MB/);
    expect(validateImageFile(f('ok.jpg', 'image/jpeg', MAX_IMAGE_BYTES))).toBe('');
  });
  it('falls back to the extension only when the browser gives no type', () => {
    expect(validateImageFile(f('photo.JPG', ''))).toBe('');
    expect(validateImageFile(f('scan.pdf', ''))).toMatch(/not supported/);
  });
  it('treats no file as fine', () => { expect(validateImageFile(undefined)).toBe(''); });
});

describe('snapshotFile', () => {
  it('copies the bytes into an in-memory file with the same identity', async () => {
    const src = new File(['hello'], 'receipt.jpg', { type: 'image/jpeg', lastModified: 42 });
    const copy = await snapshotFile(src);
    expect(copy).not.toBe(src);
    expect([copy.name, copy.type, copy.size, copy.lastModified]).toEqual(['receipt.jpg', 'image/jpeg', 5, 42]);
  });
  it('returns null when the picked file can no longer be read', async () => {
    const dead = { name: 'x.jpg', type: 'image/jpeg', size: 10, arrayBuffer: () => Promise.reject(new Error('NotReadableError')) };
    expect(await snapshotFile(dead)).toBeNull();
  });
});
