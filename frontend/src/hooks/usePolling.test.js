import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { startPolling } from './usePolling';

const setHidden = (h) => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => h }); };

describe('startPolling', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1_000_000); setHidden(false); vi.spyOn(Math, 'random').mockReturnValue(0.5); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); setHidden(false); });

  it('calls fn on the interval and stops cleanly', async () => {
    const fn = vi.fn().mockResolvedValue();
    const stop = startPolling(fn, 10000);
    await vi.advanceTimersByTimeAsync(10000); expect(fn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10000); expect(fn).toHaveBeenCalledTimes(2);
    stop();
    await vi.advanceTimersByTimeAsync(60000); expect(fn).toHaveBeenCalledTimes(2);
  });

  it('does not call while the tab is hidden, and resumes when it is visible again', async () => {
    const fn = vi.fn().mockResolvedValue();
    const stop = startPolling(fn, 10000);
    setHidden(true);
    await vi.advanceTimersByTimeAsync(50000); expect(fn).not.toHaveBeenCalled();
    setHidden(false); document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0); expect(fn).toHaveBeenCalledTimes(1);
    stop();
  });

  it('absorbs a visibility/online burst (minimum gap)', async () => {
    const fn = vi.fn().mockResolvedValue();
    const stop = startPolling(fn, 20000);          // default gap = 15 s
    await vi.advanceTimersByTimeAsync(20000); expect(fn).toHaveBeenCalledTimes(1);
    for (let i = 0; i < 5; i++) { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('online')); }
    await vi.advanceTimersByTimeAsync(0); expect(fn).toHaveBeenCalledTimes(1);   // burst ignored
    await vi.advanceTimersByTimeAsync(16000);
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0); expect(fn).toHaveBeenCalledTimes(2);   // a later return is honoured
    stop();
  });

  it('never overlaps calls', async () => {
    let inflight = 0, peak = 0;
    const fn = vi.fn(async () => { inflight++; peak = Math.max(peak, inflight); await new Promise(r => setTimeout(r, 35000)); inflight--; });
    const stop = startPolling(fn, 10000, { minGapMs: 0 });
    await vi.advanceTimersByTimeAsync(120000);
    expect(peak).toBe(1);
    stop();
  });

  it('backs off after failures and recovers after a success', async () => {
    const fn = vi.fn().mockRejectedValueOnce(new Error('x')).mockRejectedValueOnce(new Error('x')).mockResolvedValue();
    const stop = startPolling(fn, 10000);
    await vi.advanceTimersByTimeAsync(10000); expect(fn).toHaveBeenCalledTimes(1);   // fails -> next in 20 s
    await vi.advanceTimersByTimeAsync(19000); expect(fn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);  expect(fn).toHaveBeenCalledTimes(2);   // fails -> next in 40 s
    await vi.advanceTimersByTimeAsync(39000); expect(fn).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1000);  expect(fn).toHaveBeenCalledTimes(3);   // success -> back to 10 s
    await vi.advanceTimersByTimeAsync(10000); expect(fn).toHaveBeenCalledTimes(4);
    stop();
  });
});
