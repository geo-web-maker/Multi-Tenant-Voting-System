// Session persistence helpers.
//
// Why this exists: every piece of "where am I in the app" used to live only in
// React state. A reload (pull-to-refresh on a phone, an accidental F5, the
// browser discarding a background tab) wiped that state and dropped everyone
// on the voter login screen — even admins whose JWT was still perfectly valid
// in sessionStorage, and voters who had already passed OTP verification.
//
// Everything here uses sessionStorage on purpose (not localStorage): it is
// scoped to the tab, survives reloads, and disappears when the tab is closed,
// which is the right lifetime for a login session on shared lab/library PCs.
import { useEffect, useState } from 'react';
import { ADMIN_TOKEN_KEY, VOTER_TOKEN_KEY } from './api';

// ── Safe storage wrappers ────────────────────────────────────────────────
// sessionStorage can throw (Safari private mode, storage disabled, quota).
// Persistence is a convenience; it must never break the app.
const safeGet = (k) => { try { return sessionStorage.getItem(k); } catch { return null; } };
const safeSet = (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } };
const safeRemove = (k) => { try { sessionStorage.removeItem(k); } catch { /* ignore */ } };
const safeKeys = () => {
  try { return Object.keys(sessionStorage); } catch { return []; }
};

// ── Keys ─────────────────────────────────────────────────────────────────
const VOTER_PROGRESS_KEY = 'voter_progress';
const VOTER_RESEND_KEY   = 'voter_resend_deadline';
const BALLOT_PREFIX      = 'voter_ballot:';
const PUBLIC_VIEW_KEY    = 'public_view';
const PW_PENDING_KEY     = 'admin_pw_change_pending';
const TAB_PREFIX         = 'tab:';
const DRAFT_PREFIX       = 'draft:';

// The views verify-admin can hand out; each matches the `role` claim in the JWT.
const ADMIN_VIEWS = ['superadmin', 'commission', 'it_admin', 'financial_controller', 'overseer'];
const PUBLIC_VIEWS = ['results', 'apply'];

// ── Admin session ────────────────────────────────────────────────────────
function decodeJwtClaims(token) {
  try {
    const part = token.split('.')[1];
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

export function clearAdminSession() {
  [
    'admin_role', ADMIN_TOKEN_KEY, 'commissioner_id',
    'it_admin_id', 'it_admin_name',
    'financial_controller_id', 'financial_controller_name',
    'overseer_id', 'overseer_name', PW_PENDING_KEY,
  ].forEach(safeRemove);
  // Remembered dashboard tabs belong to the session that just ended.
  safeKeys().filter((k) => k.startsWith(TAB_PREFIX)).forEach(safeRemove);
}

// If a still-valid admin token is in sessionStorage, return the view (role)
// to reopen; otherwise null. The role comes from the signed token itself, not
// from a separate sessionStorage key, so the two can never disagree. The
// backend still verifies the token on every request — this only decides what
// to render first, and expired tokens are dropped here so the dashboard never
// flashes up just to 401 and bounce.
export function restoreAdminView() {
  const token = safeGet(ADMIN_TOKEN_KEY);
  if (!token) return null;

  // A forced first-login password change was in progress when the page
  // reloaded. Don't drop them into the dashboard around it — start clean.
  if (safeGet(PW_PENDING_KEY)) {
    clearAdminSession();
    return null;
  }

  const claims = decodeJwtClaims(token);
  const expired = !claims || (claims.exp && claims.exp * 1000 <= Date.now());
  if (expired || !ADMIN_VIEWS.includes(claims.role)) {
    clearAdminSession();
    return null;
  }
  return claims.role;
}

export const markPasswordChangePending = () => safeSet(PW_PENDING_KEY, '1');
export const clearPasswordChangePending = () => safeRemove(PW_PENDING_KEY);

// ── Public views (Live Results / Apply) ──────────────────────────────────
export const loadPublicView = () => {
  const v = safeGet(PUBLIC_VIEW_KEY);
  return PUBLIC_VIEWS.includes(v) ? v : null;
};
export const savePublicView = (view) => {
  if (PUBLIC_VIEWS.includes(view)) safeSet(PUBLIC_VIEW_KEY, view);
  else safeRemove(PUBLIC_VIEW_KEY);
};

// ── Voter progress ───────────────────────────────────────────────────────
// Voters don't get a JWT. The server tracks their state on the voter record
// (last_status === "authenticated" after a correct OTP, until the ballot is
// cast), so after a reload the only thing the client needs is *which* voter it
// was and which step they were on. No secrets are stored: the OTP itself is
// never persisted.
const VOTER_STEPS = [2, 3, 4];

export const saveVoterToken = (token) => {
  if (token) safeSet(VOTER_TOKEN_KEY, token);
};

export const clearVoterToken = () => safeRemove(VOTER_TOKEN_KEY);

export function loadVoterProgress() {
  try {
    const p = JSON.parse(safeGet(VOTER_PROGRESS_KEY) || 'null');
    // The ballot step is only resumable while the voter still holds the
    // session token the server issued at OTP verification — without it
    // /vote-bulk would reject them, so send them back to log in instead.
    if (p && p.step === 3 && !safeGet(VOTER_TOKEN_KEY)) return null;
    if (p && VOTER_STEPS.includes(p.step) && typeof p.studentId === 'string' && p.studentId) {
      return { step: p.step, studentId: p.studentId, selectedPhone: p.selectedPhone || '' };
    }
  } catch { /* fall through */ }
  return null;
}

export const saveVoterProgress = (p) => safeSet(VOTER_PROGRESS_KEY, JSON.stringify(p));

// Forget where the voter was and their session token, but keep any saved
// ballot picks — used when the session merely expired, so a voter who logs
// back in doesn't have to re-choose everything.
export function clearVoterSession() {
  safeRemove(VOTER_PROGRESS_KEY);
  safeRemove(VOTER_RESEND_KEY);
  safeRemove(VOTER_TOKEN_KEY);
}

// Full wipe (logout, "Vote Now", after voting): session plus saved picks.
export function clearVoterProgress() {
  clearVoterSession();
  safeKeys().filter((k) => k.startsWith(BALLOT_PREFIX)).forEach(safeRemove);
}

// "Resend SMS" cooldown, stored as an absolute deadline so it keeps counting
// down across a reload instead of resetting (or being skipped).
export const saveResendDeadline = (seconds) =>
  safeSet(VOTER_RESEND_KEY, String(Date.now() + seconds * 1000));

export function loadResendSeconds() {
  const end = Number(safeGet(VOTER_RESEND_KEY));
  if (!end) return 0;
  return Math.max(0, Math.ceil((end - Date.now()) / 1000));
}

// ── Ballot selections ────────────────────────────────────────────────────
// Selections are held only until the ballot is submitted, or the tab closes.
export function loadBallot(studentId) {
  if (!studentId) return {};
  try {
    const b = JSON.parse(safeGet(BALLOT_PREFIX + studentId) || '{}');
    return b && typeof b === 'object' && !Array.isArray(b) ? b : {};
  } catch {
    return {};
  }
}
export const saveBallot = (studentId, ballot) => {
  if (!studentId) return;
  if (Object.keys(ballot).length === 0) safeRemove(BALLOT_PREFIX + studentId);
  else safeSet(BALLOT_PREFIX + studentId, JSON.stringify(ballot));
};
export const clearBallot = (studentId) => safeRemove(BALLOT_PREFIX + studentId);

// ── Generic persisted state ──────────────────────────────────────────────
// Drop-in replacement for useState that survives a reload. Used for the
// active dashboard tab (wiped on admin logout).
function usePersisted(prefix, key, initial) {
  const storageKey = prefix + key;
  const [value, setValue] = useState(() => {
    const raw = safeGet(storageKey);
    if (raw == null) return initial;
    try { return JSON.parse(raw); } catch { return initial; }
  });
  useEffect(() => {
    safeSet(storageKey, JSON.stringify(value));
  }, [storageKey, value]);
  return [value, setValue];
}

export const usePersistedTab = (key, initial) => usePersisted(TAB_PREFIX, key, initial);

// ── Form drafts ──────────────────────────────────────────────────────────
// Plain JSON-safe fields only. Never pass a File/Blob — those can't be
// serialised, so photo and payment-proof uploads must be re-selected.
export function loadDraft(key) {
  try {
    const d = JSON.parse(safeGet(DRAFT_PREFIX + key) || 'null');
    return d && typeof d === 'object' ? d : null;
  } catch {
    return null;
  }
}
export const saveDraft = (key, data) => safeSet(DRAFT_PREFIX + key, JSON.stringify(data));
export const clearDraft = (key) => safeRemove(DRAFT_PREFIX + key);
