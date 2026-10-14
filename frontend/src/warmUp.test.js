import { describe, it, expect, vi, beforeEach } from 'vitest';
vi.mock('./api', () => ({ default: { get: vi.fn() } }));
import api from './api';
import { warmUp, _setLastOkForTests } from './warmUp';

describe('warmUp', () => {
  beforeEach(() => { api.get.mockReset(); });
  it('does nothing while the connection is fresh', async () => {
    _setLastOkForTests(Date.now());
    expect(await warmUp()).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });
  it('sends one /health GET after a long idle', async () => {
    _setLastOkForTests(Date.now() - 5 * 60_000);
    api.get.mockResolvedValue({});
    expect(await warmUp()).toBe(true);
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get.mock.calls[0][0]).toBe('/health');
  });
  it('never throws when the warm-up itself fails', async () => {
    _setLastOkForTests(0);
    api.get.mockRejectedValue(new Error('Network Error'));
    await expect(warmUp()).resolves.toBe(true);
  });
});
