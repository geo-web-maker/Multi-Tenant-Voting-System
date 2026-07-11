import axios from 'axios';

// Base URL for the backend API — same env var every component already uses.
export const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

// The org slug for this deployment, set at build time per-org.
// Example: an org's Vercel deployment sets VITE_ORG_SLUG=kyuccu in its .env.
// Left unset, requests carry no X-Org-Slug header and the backend falls back
// to its legacy/default (non-multi-tenant) behavior automatically.
export const ORG_SLUG = import.meta.env.VITE_ORG_SLUG || "";

// Shared axios instance. Every component should import `api` from here
// instead of importing axios directly, so every request automatically
// carries the org context without each call site having to remember to add it.
const api = axios.create({
  baseURL: API_BASE,
});

api.interceptors.request.use((config) => {
  if (ORG_SLUG) {
    config.headers['X-Org-Slug'] = ORG_SLUG;
  }
  return config;
});

export default api;
