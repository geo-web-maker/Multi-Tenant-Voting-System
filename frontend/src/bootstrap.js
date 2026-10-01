import api from './api';

/**
 * E1: one startup request for branding + election status + positions (GET /public/bootstrap).
 * App and the Apply form both need these within moments of each other, so concurrent / near-in-time callers
 * share one request (TTL below). If the endpoint is unavailable (older backend, network blip) each part falls
 * back to the original endpoint, so nothing here can stop a page from loading.
 */
const TTL_MS = 10000;
let cached = null;   // { at, promise }

async function viaOldEndpoints() {
  const [branding, status, positions] = await Promise.all([
    api.get('/superadmin/branding').then(r => r.data).catch(() => null),
    api.get('/election-status').then(r => r.data).catch(() => null),
    api.get('/positions').then(r => r.data).catch(() => null),
  ]);
  return { branding, status, positions };
}

export function fetchBootstrap({ fresh = false } = {}) {
  const now = Date.now();
  if (!fresh && cached && now - cached.at < TTL_MS) return cached.promise;
  const promise = api.get('/public/bootstrap')
    .then(r => ({ branding: r.data?.branding ?? null, status: r.data?.status ?? null, positions: r.data?.positions ?? null }))
    .catch(viaOldEndpoints);
  cached = { at: now, promise };
  return promise;
}

export function resetBootstrapCache() { cached = null; }
