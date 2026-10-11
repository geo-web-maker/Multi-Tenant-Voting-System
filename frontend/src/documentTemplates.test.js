import { describe, it, expect } from 'vitest';
import { DOCUMENT_TEMPLATES, resolveDocTemplate, isLandscape, docFileName, sealInk, sealAccent } from './documentTemplates';

describe('document templates', () => {
  it('offers classic and formal, and anything unknown resolves to classic', () => {
    expect(DOCUMENT_TEMPLATES.map((t) => t.id)).toEqual(['classic', 'formal']);
    expect(resolveDocTemplate('formal')).toBe('formal');
    expect(resolveDocTemplate(undefined)).toBe('classic');
    expect(resolveDocTemplate('blueprint')).toBe('classic');
  });

  it('only the formal template prints landscape', () => {
    expect(isLandscape('formal')).toBe(true);
    expect(isLandscape('classic')).toBe(false);
    expect(isLandscape(undefined)).toBe(false);
  });

  it('names the PDF "name - document - organisation" and strips characters files cannot hold', () => {
    expect(docFileName('Certificate of Nomination', 'jane namukasa', 'Kyambogo University Engineering Society'))
      .toBe('Jane Namukasa - Certificate of Nomination - Kyambogo University Engineering Society');
    expect(docFileName('Decision Notice', 'A/B: C', 'Org*')).toBe('A B C - Decision Notice - Org');
    expect(docFileName('Decision Notice', '', 'Org')).toBe('Decision Notice - Org');
  });

  it('keeps seal ink readable and the accent visible on white', () => {
    expect(sealInk('#003366')).toBe('#003366');
    expect(sealInk('#f1c40f')).toBe('#14305a');
    expect(sealInk('not a colour')).toBe('#14305a');
    expect(sealAccent('#f1c40f')).not.toBe('#f1c40f');
    expect(sealAccent('')).toBe('#b8860b');
  });
});
