import { describe, it, expect } from 'vitest';
import { buildIdText, DEFAULT_ID_LABEL, setIdText, patchIdText, getIdText } from './idText';

describe('buildIdText', () => {
  it('keeps the original wording when nothing is configured', () => {
    const t = buildIdText({});
    expect(t.label).toBe(DEFAULT_ID_LABEL);
    expect(t.noun).toBe('registration number');
    expect(t.hint).toContain('23/U/XXX/00000/GV');
  });
  it('uses the org label and examples, and never shows another org\'s format', () => {
    const t = buildIdText({ id_label: 'Student Number', id_examples: ['2100712345', '2200798765'] });
    expect(t.label).toBe('Student Number');
    expect(t.noun).toBe('student number');
    expect(t.nounCap).toBe('Student number');
    expect(t.ids).toEqual(['2100712345', '2200798765']);
    expect(t.hint).toContain('2100712345');
    expect(t.hint).not.toContain('23/U');
  });
  it('a custom label with no examples gets no borrowed format hint', () => {
    expect(buildIdText({ id_label: 'Student Number' }).hint).toBe('');
  });
  it('an explicit hint wins', () => {
    expect(buildIdText({ id_label: 'Student Number', id_format_hint: 'Ten digits, no spaces.' }).hint).toBe('Ten digits, no spaces.');
  });
  it('ignores blanks in the lists', () => {
    expect(buildIdText({ name_examples: ['', '  ', 'Okello Sam'] }).names).toEqual(['Okello Sam']);
  });
  it('short title stays "Registration Number" by default and follows a custom label', () => {
    expect(buildIdText({}).short).toBe('Registration Number');
    expect(buildIdText({ id_label: 'Student Number' }).short).toBe('Student Number');
  });
  it('patchIdText changes the label and keeps the examples', () => {
    setIdText({ id_label: '', id_examples: ['2100712345'] });
    patchIdText({ id_label: 'Student Number' });
    expect(getIdText().label).toBe('Student Number');
    expect(getIdText().ids).toEqual(['2100712345']);
    setIdText(null);
  });
});
