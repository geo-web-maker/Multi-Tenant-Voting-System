import { afterEach, describe, expect, it, vi } from 'vitest';
import { safeLocalStorage, safeSessionStorage } from './storage.js';

afterEach(() => {
  vi.restoreAllMocks();
  safeSessionStorage.clear();
  safeLocalStorage.clear();
});

describe('safe storage', () => {
  it('keeps same-page reads working when browser storage writes are blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage access denied');
    });

    safeSessionStorage.setItem('storage-test-session', 'session-value');
    safeLocalStorage.setItem('storage-test-local', 'local-value');

    expect(safeSessionStorage.getItem('storage-test-session')).toBe('session-value');
    expect(safeLocalStorage.getItem('storage-test-local')).toBe('local-value');
    expect(safeSessionStorage.key(0)).not.toBeNull();
  });

  it('supports remove and clear without relying on native storage access', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage access denied');
    });

    safeSessionStorage.setItem('storage-test-remove', 'value');
    safeSessionStorage.removeItem('storage-test-remove');
    expect(safeSessionStorage.getItem('storage-test-remove')).toBeNull();

    safeLocalStorage.setItem('storage-test-clear', 'value');
    safeLocalStorage.clear();
    expect(safeLocalStorage.getItem('storage-test-clear')).toBeNull();
  });
});
