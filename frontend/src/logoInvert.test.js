import { describe, it, expect } from 'vitest';
import { logoNeedsInvertFromPixels as f } from './logoInvert';

const px = (list) => Uint8ClampedArray.from(list.flatMap(([r, g, b, a = 255, n = 1]) => Array(n).fill([r, g, b, a]).flat()));

describe('logoNeedsInvertFromPixels', () => {
  it('inverts black line-art on a transparent background', () => {
    expect(f(px([[0, 0, 0, 255, 90], [30, 30, 30, 255, 10], [0, 0, 0, 0, 500]]))).toBe(true);
  });
  it('does NOT invert a full-colour badge with a black ring (red gear, black ring)', () => {
    expect(f(px([[0, 0, 0, 255, 70], [169, 13, 24, 255, 30], [0, 0, 0, 0, 100]]))).toBe(false);
  });
  it('does not invert a light logo', () => {
    expect(f(px([[240, 240, 240, 255, 100]]))).toBe(false);
  });
  it('does not invert an empty / fully transparent image', () => {
    expect(f(px([[0, 0, 0, 0, 50]]))).toBe(false);
    expect(f(new Uint8ClampedArray(0))).toBe(false);
  });
});
