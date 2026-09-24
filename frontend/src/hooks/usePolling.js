import { useEffect, useRef } from 'react';

/**
 * Keep a screen fresh without the user pressing Refresh.
 *
 * Calls `fn` every `intervalMs` while the tab is visible, and once immediately when the tab becomes
 * visible again or the browser comes back online (so a page left in the background is current the
 * moment it is looked at). Never runs two calls at once, and always uses the latest `fn`, so callers
 * can pass a fresh inline function every render without restarting the timer.
 *
 * `fn` should refresh quietly (no spinners / "Syncing…") — pass { silent: true } style logic in the caller.
 * Pass `enabled = false` to pause (e.g. while a form is being edited).
 */
export default function usePolling(fn, intervalMs = 20000, enabled = true) {
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });

  useEffect(() => {
    if (!enabled || !intervalMs) return undefined;
    let running = false;
    let stopped = false;
    const tick = async () => {
      if (running || stopped || document.hidden) return;
      running = true;
      try { await fnRef.current(); } catch { /* a failed background refresh is not worth interrupting the user */ }
      finally { running = false; }
    };
    const id = setInterval(tick, intervalMs);
    const onVisible = () => { if (!document.hidden) tick(); };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('online', tick);
    return () => {
      stopped = true;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('online', tick);
    };
  }, [intervalMs, enabled]);
}
