import { useEffect, useRef } from 'react';

/**
 * Non-hook core, for call sites that already live inside an effect (one implementation for all of them).
 *
 * Calls `fn` every `intervalMs` while the tab is visible, and once when the tab becomes visible again or the
 * browser comes back online — but never twice within `minGapMs`, so someone bouncing to their Mobile Money
 * app and back can't trigger a burst of refetches. Never runs two calls at once. If `fn` throws, the next
 * delay doubles (up to 4x) until it succeeds again. Delays carry +/-10 % jitter. Returns `stop()`.
 *
 * `minGapMs` defaults to 80 % of the interval (capped at 15 s): large enough to absorb visibility/online
 * bursts, small enough that the regular timer tick is never the one that gets skipped.
 */
export function startPolling(fn, intervalMs, { minGapMs } = {}) {
  const gap = minGapMs ?? Math.min(15000, Math.round(intervalMs * 0.8));
  let running = false, stopped = false, last = 0, fails = 0, timer = null;

  const schedule = () => {
    if (stopped) return;
    clearTimeout(timer);
    const wait = intervalMs * Math.min(4, 2 ** fails) * (0.9 + Math.random() * 0.2);
    timer = setTimeout(() => tick(), wait);
  };
  const tick = async () => {
    if (stopped) return;
    if (running || document.hidden || Date.now() - last < gap) { schedule(); return; }
    running = true; last = Date.now();
    try { await fn(); fails = 0; } catch { fails += 1; }   // a failed background refresh must not interrupt the user
    finally { running = false; }
    schedule();
  };
  const onWake = () => { if (!document.hidden) tick(); };
  schedule();
  document.addEventListener('visibilitychange', onWake);
  window.addEventListener('online', onWake);
  return () => {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener('visibilitychange', onWake);
    window.removeEventListener('online', onWake);
  };
}

/**
 * Keep a screen fresh without the user pressing Refresh. Always uses the latest `fn`, so callers can pass a
 * fresh inline function every render without restarting the timer.
 *
 * `fn` should refresh quietly (no spinners / "Syncing…"). Pass `enabled = false` to pause (e.g. while a form
 * is being edited, or once results are final). `options.minGapMs` overrides the burst guard.
 */
export default function usePolling(fn, intervalMs = 20000, enabled = true, options) {
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  const minGapMs = options?.minGapMs;

  useEffect(() => {
    if (!enabled || !intervalMs) return undefined;
    return startPolling(() => fnRef.current(), intervalMs, { minGapMs });
  }, [intervalMs, enabled, minGapMs]);
}
