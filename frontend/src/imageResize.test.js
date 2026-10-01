import { describe, it, expect, vi, afterEach } from 'vitest';
import { fitWithin, resizeImage } from './imageResize';

afterEach(() => { vi.unstubAllGlobals(); });
const big = (type = 'image/jpeg') => new File([new Uint8Array(2 * 1024 * 1024)], 'photo.png', { type });

describe('B4: fitWithin', () => {
  it('scales the longest side to max, keeps ratio', () => {
    expect(fitWithin(4000, 3000, 1600)).toEqual({ width: 1600, height: 1200 });
    expect(fitWithin(3000, 4000, 1600)).toEqual({ width: 1200, height: 1600 });
  });
  it('never scales up', () => expect(fitWithin(800, 600, 1600)).toEqual({ width: 800, height: 600 }));
  it('never returns 0', () => expect(fitWithin(10000, 1, 1600).height).toBe(1));
});

describe('B4: resizeImage fallbacks', () => {
  it('returns the original when createImageBitmap throws', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('HEIC')));
    const f = big();
    expect(await resizeImage(f)).toBe(f);
  });
  it('skips non-images, GIFs and files under 1 MB without decoding', async () => {
    const spy = vi.fn();
    vi.stubGlobal('createImageBitmap', spy);
    const small = new File([new Uint8Array(10)], 's.jpg', { type: 'image/jpeg' });
    const pdf = new File([new Uint8Array(2e6)], 'a.pdf', { type: 'application/pdf' });
    expect(await resizeImage(small)).toBe(small);
    expect(await resizeImage(pdf)).toBe(pdf);
    const gif = big('image/gif');
    expect(await resizeImage(gif)).toBe(gif);
    expect(spy).not.toHaveBeenCalled();
  });
  it('returns a smaller JPEG when decoding works', async () => {
    const close = vi.fn();
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 4000, height: 3000, close }));
    const ctx = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: '' };
    const spyCanvas = vi.spyOn(document, 'createElement').mockImplementation((tag) => (tag === 'canvas'
      ? { getContext: () => ctx, toBlob: (cb) => cb(new Blob([new Uint8Array(1000)], { type: 'image/jpeg' })), width: 0, height: 0 }
      : Document.prototype.createElement.call(document, tag)));
    const out = await resizeImage(big());
    spyCanvas.mockRestore();
    expect(out.type).toBe('image/jpeg');
    expect(out.name).toBe('photo.jpg');
    expect(out.size).toBe(1000);
    expect(ctx.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 1600, 1200);
    expect(close).toHaveBeenCalled();
  });
  it('keeps the original when the result is not smaller', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 100, height: 100 }));
    const ctx = { fillRect() {}, drawImage() {} };
    const spyCanvas = vi.spyOn(document, 'createElement').mockImplementation((tag) => (tag === 'canvas'
      ? { getContext: () => ctx, toBlob: (cb) => cb(new Blob([new Uint8Array(5 * 1024 * 1024)])), width: 0, height: 0 }
      : Document.prototype.createElement.call(document, tag)));
    const f = big();
    const out = await resizeImage(f);
    spyCanvas.mockRestore();
    expect(out).toBe(f);
  });
});
