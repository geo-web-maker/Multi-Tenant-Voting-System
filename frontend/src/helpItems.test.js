import { describe, it, expect } from 'vitest';
import { helpItemsFor, showHelpFab, supportReasonsFor, HELP_TRACK, isTextEntry } from './helpItems';

describe('A2: helpItemsFor', () => {
  it('voter list', () => {
    expect(helpItemsFor('voter')).toEqual(['code-note', 'sample-ballot', 'register', 'timeline', 'support']);
  });
  it('apply list', () => {
    expect(helpItemsFor('apply')).toEqual(['register', 'timeline', 'fees', 'support']);
  });
  it('Sample Ballot only on voter, Nomination Fees only on apply', () => {
    expect(helpItemsFor('voter')).toContain('sample-ballot');
    expect(helpItemsFor('apply')).not.toContain('sample-ballot');
    expect(helpItemsFor('apply')).toContain('fees');
    expect(helpItemsFor('voter')).not.toContain('fees');
  });
  it('the voter-code note is not shown on apply', () => {
    expect(helpItemsFor('apply')).not.toContain('code-note');
  });
  it('an unknown page falls back to the voter list, and callers cannot mutate the table', () => {
    expect(helpItemsFor('results')).toEqual(helpItemsFor('voter'));
    helpItemsFor('voter').push('x');
    expect(helpItemsFor('voter')).not.toContain('x');
  });
});

describe('A2: showHelpFab', () => {
  it('voter steps 1, 2 and 4 show it, step 3 (ballot) does not', () => {
    expect([1, 2, 4].every((st) => showHelpFab('voter', st))).toBe(true);
    expect(showHelpFab('voter', 3)).toBe(false);
  });
  it('apply shows it at any step', () => {
    expect(showHelpFab('apply', 3)).toBe(true);
    expect(showHelpFab('apply', 1)).toBe(true);
  });
  it('other views do not', () => {
    expect(showHelpFab('results', 1)).toBe(false);
    expect(showHelpFab('admin', 1)).toBe(false);
  });
});

describe('A2 extras: helpers', () => {
  it('support reasons: two on apply, none on voter', () => {
    expect(supportReasonsFor('apply')).toEqual(['Application problem', 'Payment']);
    expect(supportReasonsFor('voter')).toEqual([]);
  });
  it('track ids are the agreed four and pass the tracker label rule', () => {
    expect(HELP_TRACK).toEqual({ fab: 'help-fab', fees: 'help-fees', timeline: 'help-timeline', support: 'help-support' });
    Object.values(HELP_TRACK).forEach((id) => expect(/^[a-z0-9_-]{2,40}$/.test(id)).toBe(true));
  });
  it('isTextEntry: text-like fields yes, buttons and checkboxes no', () => {
    const el = (tagName, type) => ({ tagName, type });
    expect(isTextEntry(el('INPUT', 'text'))).toBe(true);
    expect(isTextEntry(el('TEXTAREA'))).toBe(true);
    expect(isTextEntry(el('SELECT', 'select-one'))).toBe(true);
    expect(isTextEntry(el('INPUT', 'checkbox'))).toBe(false);
    expect(isTextEntry(el('INPUT', 'file'))).toBe(false);
    expect(isTextEntry(el('BUTTON', 'submit'))).toBe(false);
    expect(isTextEntry(null)).toBe(false);
  });
});
