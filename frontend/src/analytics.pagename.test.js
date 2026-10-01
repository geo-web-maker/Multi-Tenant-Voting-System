import { describe, it, expect } from 'vitest';
import { pageName } from './analytics';

describe('pageName', () => {
  it('names the staff login separately from the voter identity page', () => {
    expect(pageName('voter', 1, true)).toBe('admin_login');
    expect(pageName('voter', 2, true)).toBe('admin_login');
    expect(pageName('voter', 1, false)).toBe('voter_identity');
    expect(pageName('voter', 3)).toBe('voter_ballot');
  });
  it('leaves other views alone', () => {
    expect(pageName('results', 1, true)).toBe('results');
    expect(pageName('apply', 1)).toBe('apply');
  });
});
