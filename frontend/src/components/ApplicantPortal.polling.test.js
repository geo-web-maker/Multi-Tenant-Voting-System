import { describe, it, expect } from 'vitest';
import src from './ApplicantPortal.jsx?raw';

// B5 / WP-4 remainder: the portal refreshes through the shared usePolling hook (burst guard, pause in a
// hidden tab, no overlapping calls), never a hand-rolled timer.
describe('B5 ApplicantPortal polling', () => {
  it('has no raw setInterval', () => {
    expect(src).not.toMatch(/setInterval\s*\(/);
  });
  it('polls through the shared usePolling hook', () => {
    expect(src).toMatch(/import usePolling from '\.\.\/hooks\/usePolling'/);
    expect(src).toMatch(/usePolling\(/);
  });
  it('stops polling once the application is submitted', () => {
    expect(src).toMatch(/,\s*20000,\s*!submitted\s*\)/);
  });
});
