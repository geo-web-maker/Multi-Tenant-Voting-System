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

// Shared axios instance. Every component should import `api` from here
// instead of importing axios directly, so every request automatically
// carries the org context and admin session token without each call site
// having to remember to add it.
const api = axios.create({
  baseURL: API_BASE,
});

api.interceptors.request.use((config) => {
  const activeSlug = sessionStorage.getItem(SUPERADMIN_ORG_OVERRIDE_KEY) || ORG_SLUG;
  if (activeSlug) {
    config.headers['X-Org-Slug'] = activeSlug;
  }
  const token = sessionStorage.getItem(ADMIN_TOKEN_KEY);
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
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
  (response) => response,
  (error) => {
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

export default api;

