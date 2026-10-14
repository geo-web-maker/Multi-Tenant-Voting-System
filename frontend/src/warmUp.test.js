import { describe, it, expect, vi, beforeEach } from 'vitest';
vi.mock('./api', () => ({ default: { get: vi.fn() } }));
import api from './api';
import { warmUp, wakeServer, _setLastOkForTests } from './warmUp';

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
  it('wakeServer keeps asking until /health answers', async () => {
    _setLastOkForTests(0);
    api.get.mockRejectedValueOnce(new Error('x')).mockRejectedValueOnce(new Error('x')).mockResolvedValue({});
    expect(await wakeServer({ gapMs: 0 })).toBe(true);
    expect(api.get).toHaveBeenCalledTimes(3);
  });
  it('wakeServer gives up quietly after its attempts', async () => {
    _setLastOkForTests(0);
    api.get.mockRejectedValue(new Error('x'));
    await expect(wakeServer({ gapMs: 0 })).resolves.toBe(true);
    expect(api.get).toHaveBeenCalledTimes(3);
  });
  it('wakeServer skips when the API answered moments ago', async () => {
    _setLastOkForTests(Date.now());
    expect(await wakeServer()).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });
});
