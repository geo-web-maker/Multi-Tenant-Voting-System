import api from './api';

// A page left open for a while goes stale in a way nothing on screen shows: the phone may have frozen the tab, the
// connection it kept open is dead, or the free-tier backend has gone to sleep. The first request after that fails
// with no response, and a submit (a POST, which is never auto-retried) is the request that pays for it.
// Calling this just before a submit sends one cheap GET first, which wakes the server and replaces the dead
// connection, so the real request goes out on a good one. GETs are retried by api.js already.
const IDLE_MS = 60_000;
let lastOkAt = Date.now();
if (typeof window !== 'undefined') {
  window.addEventListener('an:api', (e) => { if (e?.detail?.ok) lastOkAt = Date.now(); });
}

/** True when the connection has been quiet long enough that it may be dead. Synchronous, so callers only wait when they must. */
export const isIdle = ({ idleMs = IDLE_MS, now = Date.now() } = {}) => now - lastOkAt >= idleMs;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * @param {{idleMs?: number, now?: number, attempts?: number, gapMs?: number}} [o]
 * attempts > 1 keeps asking until /health answers: a sleeping free-tier backend can take 30 s+ to boot, longer than one
 * request waits, so a single try would just fail and the real request would hit the same sleeping server.
 * @returns {Promise<boolean>} true when a warm-up request was needed. Never throws: the real request reports its own error. */
export async function warmUp({ idleMs = IDLE_MS, now = Date.now(), attempts = 1, gapMs = 2000 } = {}) {
  if (now - lastOkAt < idleMs) return false;
  for (let i = 0; i < attempts; i++) {
    try { await api.get('/health', { timeout: attempts > 1 ? 15000 : 10000, ...(attempts > 1 ? { __noRetry: true } : {}) }); return true; }
    catch { if (i < attempts - 1) await sleep(gapMs); }
  }
  return true;
}

/** Wake the server before a request that must not fail (an application submit, an upload retry). Skipped if the API answered in the last 15 s. */
export const wakeServer = (o = {}) => warmUp({ idleMs: 15_000, attempts: 3, ...o });

export const _setLastOkForTests = (t) => { lastOkAt = t; };
