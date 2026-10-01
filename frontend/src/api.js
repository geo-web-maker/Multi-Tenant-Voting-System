import axios from 'axios';

// Base URL for the backend API — same env var every component already uses.
export const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

// The org slug for this deployment, set at build time per-org.
// Example: an org's Vercel deployment sets VITE_ORG_SLUG=kyuccu in its .env.
// Left unset, requests carry no X-Org-Slug header and the backend falls back
// to its legacy/default (non-multi-tenant) behavior automatically.
export const ORG_SLUG = import.meta.env.VITE_ORG_SLUG || "";

// sessionStorage key the Superadmin org-switcher dropdown writes to. This lets
// one logged-in superadmin flip between organizations at runtime, without a
// rebuild/redeploy. It only ever affects the browser tab that set it — every
// other role (voters, commissioners, IT admins, etc.) never touches this key,
// so their requests keep using the build-time ORG_SLUG exactly as before.
export const SUPERADMIN_ORG_OVERRIDE_KEY = 'superadmin_active_org_slug';

// sessionStorage key the admin JWT (issued by /verify-admin) is stored under.
// Set on login, cleared on logout, read here on every request.
export const ADMIN_TOKEN_KEY = 'admin_token';

// sessionStorage key for the voter session token returned by /verify-otp.
// It is required by /vote and /vote-bulk (sent as X-Voter-Token) and is
// deliberately NOT the admin bearer token: voters never touch the admin
// Authorization header, so a rejected voter token can't trigger the admin
// 401 -> reload handling below.
export const VOTER_TOKEN_KEY = 'voter_token';

// Shared axios instance. Every component should import `api` from here
// instead of importing axios directly, so every request automatically
// carries the org context and admin session token without each call site
// having to remember to add it.
// Timeouts. Without one, a request on a dead 3G link hangs forever and the UI just spins. These are
// deliberately generous — the backend can take 30-50s to cold-start — and reads are retried below, so a
// slow first attempt that times out is followed by one that finds the server awake.
export const DEFAULT_TIMEOUT_MS = 30000;
const UPLOAD_TIMEOUT_MS = 120000;   // multipart bodies (photos, rosters) need far longer on slow links
const VOTE_TIMEOUT_MS = 60000;      // a cast ballot is never auto-retried, so give it room to finish

// Retry policy: ONLY idempotent reads (GET/HEAD/OPTIONS), ONLY for "the network or gateway hiccuped"
// failures, at most MAX_RETRIES extra attempts. Writes (and above all /vote) are never retried here — a
// replayed POST can double-apply; a human re-submitting after a clear error message is the safe path.
// Opt a single call out with { __noRetry: true } (e.g. /health, which has its own polling loop).
export const retryConfig = { max: 2, baseMs: 400 };
const RETRYABLE_STATUS = new Set([502, 503, 504]);
const IDEMPOTENT = new Set(['get', 'head', 'options']);

const api = axios.create({
  baseURL: API_BASE,
  timeout: DEFAULT_TIMEOUT_MS,
});

// Analytics hygiene (guide 5.1/5.2): the route without its query string, and a network-failure report that is
// neither triggered by the boot /health wake-up loop (which retries every 2.5 s by design) nor repeated for every
// retry of the same call — at most one per route per 30 s.
const routeOf = (config) => String(config?.url || '').split('?')[0];
const NETFAIL_GAP_MS = 30000;
const lastNetFail = new Map();
export function shouldReportNetFail(url, now = Date.now()) {
  if (url === '/health') return false;
  if (lastNetFail.has(url) && now - lastNetFail.get(url) < NETFAIL_GAP_MS) return false;
  lastNetFail.set(url, now);
  return true;
}
export const _resetNetFailForTests = () => lastNetFail.clear();

api.interceptors.request.use((config) => {
  config.__an_started = performance.now();
  // "View as" tab: refuse writes before they leave the browser (the server also rejects them).
  if (sessionStorage.getItem('view_as') && !['get', 'head', 'options'].includes((config.method || 'get').toLowerCase())) {
    return Promise.reject({ config, response: { status: 403, data: { detail: 'Read-only view: this action is disabled.' } } });
  }
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    config.timeout = Math.max(config.timeout || 0, UPLOAD_TIMEOUT_MS);
  } else if (config.url && config.url.startsWith('/vote')) {
    config.timeout = Math.max(config.timeout || 0, VOTE_TIMEOUT_MS);
  }
  const activeSlug = sessionStorage.getItem(SUPERADMIN_ORG_OVERRIDE_KEY) || ORG_SLUG;
  if (activeSlug) {
    config.headers['X-Org-Slug'] = activeSlug;
  }
  const token = sessionStorage.getItem(ADMIN_TOKEN_KEY);
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  // Only the ballot-casting endpoints need the voter token; don't attach it
  // to unrelated requests.
  if (config.url && config.url.startsWith('/vote')) {
    const voterToken = sessionStorage.getItem(VOTER_TOKEN_KEY);
    if (voterToken) {
      config.headers['X-Voter-Token'] = voterToken;
    }
  }
  return config;
});

// If an authenticated admin request gets a 401, the token is dead — clear
// the stale session and reload back to login rather than leaving the user
// stuck on a dashboard that will 401 on every subsequent action.
//
// IMPORTANT: only do this when the request that failed actually carried an
// Authorization header. Plenty of calls (branding fetch on page load,
// election-status, candidates list, etc.) are intentionally public and
// never had a token to begin with — a 401 there just means "not logged in
// yet", not "your session died". Reloading unconditionally on any 401 turns
// a single public-endpoint auth mistake into an infinite reload loop: the
// reload remounts the app, the same public call fires again, 401s again,
// reloads again. This check is what stops that class of bug from cascading
// even if a future endpoint is accidentally over-protected again.
api.interceptors.response.use(
  (response) => {
    if (typeof window !== 'undefined') {
      const ms = performance.now() - (response.config?.__an_started || performance.now());
      window.dispatchEvent(new CustomEvent('an:api', { detail: { ms, failed: false, ok: true, url: routeOf(response.config) } }));
    }
    return response;
  },
  (error) => {
    if (typeof window !== 'undefined') {
      const ms = performance.now() - (error.config?.__an_started || performance.now());
      const url = routeOf(error.config);
      window.dispatchEvent(new CustomEvent('an:api', { detail: { ms, failed: !error.response, ok: false, url } }));
      if (!error.response && shouldReportNetFail(url)) window.dispatchEvent(new CustomEvent('an:netfail', { detail: { kind: error.code === 'ECONNABORTED' ? 'timeout' : 'network' } }));
    }
    const hadToken = Boolean(error.config?.headers?.Authorization);
    if (error.response && error.response.status === 401 && hadToken) {
      sessionStorage.removeItem(ADMIN_TOKEN_KEY);
      sessionStorage.removeItem('admin_role');
      if (typeof window !== 'undefined' && !window.location.pathname.includes('login')) {
        window.location.reload();
      }
    }
    return Promise.reject(error);
  }
);

// Registered AFTER the handler above on purpose: that one sees (and reports) every individual attempt,
// this one decides whether to try again. Backoff is exponential with jitter so a fleet of phones that all
// lost signal together doesn't hammer the server in lockstep when it returns.
api.interceptors.response.use(undefined, async (error) => {
  const cfg = error?.config;
  if (!cfg || cfg.__noRetry || !IDEMPOTENT.has((cfg.method || 'get').toLowerCase())) return Promise.reject(error);
  if (error.code === 'ERR_CANCELED') return Promise.reject(error);
  const transient = error.response ? RETRYABLE_STATUS.has(error.response.status) : true;
  if (!transient) return Promise.reject(error);
  // Offline: retrying can't help. Polling / the browser's 'online' event will refresh when signal returns.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return Promise.reject(error);
  cfg.__retries = (cfg.__retries || 0) + 1;
  if (cfg.__retries > retryConfig.max) return Promise.reject(error);
  const wait = retryConfig.baseMs * 2 ** (cfg.__retries - 1) * (0.75 + Math.random() * 0.5);
  await new Promise((resolve) => setTimeout(resolve, wait));
  return api.request(cfg);
});

// Shared helper so every catch block surfaces the backend's actual error
// detail (e.g. "This code has expired. Please request a new one.") instead
// of a generic fallback string. The backend is disciplined about sending
// specific, actionable `detail` messages — several call sites here used to
// throw that away in favor of a flat "X failed." string, which meant the
// admin never found out *why* something failed (validation error? already
// resolved by someone else? a 409 from the new concurrency guards?) without
// opening devtools. Always prefer err.response.data.detail; fall back only
// when the backend genuinely didn't send one (network error, 5xx with no body).
export function getErrorMessage(err, fallback) {
  return err?.response?.data?.detail || fallback;
}

export default api;

