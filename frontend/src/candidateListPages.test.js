import { describe, it, expect } from 'vitest';
import { paginate, FIRST_PAGE_LINES, NEXT_PAGE_LINES, nameLines, headingLines } from './candidateListPages';

const names = (n, p = 'N') => Array.from({ length: n }, (_, i) => `${p}${i + 1}`);

describe('paginate', () => {
  it('keeps a short list on one page', () => {
    const pages = paginate([{ position: 'Chair', names: ['A', 'B'] }, { position: 'Treasurer', names: ['C'] }]);
    expect(pages).toHaveLength(1);
    expect(pages[0].map((x) => x.position)).toEqual(['Chair', 'Treasurer']);
  });

  it('always returns one (empty) page so the sheet still renders', () => {
    expect(paginate([])).toEqual([[]]);
  });

  it('splits a long position, marks it continued and keeps the numbering', () => {
    const pages = paginate([{ position: 'Delegate', names: names(40) }]);
    expect(pages.length).toBeGreaterThan(1);
    expect(pages[0][0]).toMatchObject({ continued: false, startIndex: 0 });
    expect(pages[1][0]).toMatchObject({ continued: true, startIndex: pages[0][0].names.length });
    expect(pages.flat().flatMap((x) => x.names)).toEqual(names(40));
  });

  it('never exceeds a page, and never leaves a heading with no name under it', () => {
    const sections = Array.from({ length: 9 }, (_, i) => ({ position: `P${i}`, names: names(4, `p${i}-`) }));
    const pages = paginate(sections);
    pages.forEach((page, i) => {
      const lines = page.reduce((n, x) => n + 2 + x.names.length, 0);
      expect(lines).toBeLessThanOrEqual(i === 0 ? FIRST_PAGE_LINES : NEXT_PAGE_LINES);
      page.forEach((x) => expect(x.names.length).toBeGreaterThan(0));
    });
    expect(pages.flat().flatMap((x) => x.names)).toHaveLength(36);
  });
});

describe('paginate with long text', () => {
  const cost = (page) => page.reduce((n, x) => n + headingLines(x.position, x.continued) + x.names.reduce((m, nm) => m + nameLines(nm), 0), 0);
  const long = (i) => `Namukasa Josephine Ssekitoleko-Nakimuli Byaruhanga Emmanuel Kiiza ${i}`; // wraps to 2 lines
  it('counts wrapped names as several lines so a page never overflows', () => {
    const pages = paginate([{ position: 'Representative of Persons with Disabilities and Special Needs', names: Array.from({ length: 30 }, (_, i) => long(i)) }]);
    pages.forEach((p, i) => expect(cost(p)).toBeLessThanOrEqual(i === 0 ? FIRST_PAGE_LINES : NEXT_PAGE_LINES));
    expect(pages.flat().flatMap((x) => x.names)).toHaveLength(30);
  });
  it('still places a single oversized name instead of looping', () => {
    const pages = paginate([{ position: 'P', names: ['x'.repeat(500)] }]);
    expect(pages.flat().flatMap((x) => x.names)).toHaveLength(1);
  });
  it('short names cost one line, as before', () => {
    expect(nameLines('Okello Daniel')).toBe(1);
    expect(headingLines('Chair')).toBe(2);
  });
});
