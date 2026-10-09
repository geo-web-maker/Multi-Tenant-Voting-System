// Pure helpers for the blueprint primitives (kept out of the .jsx so fast-refresh lint stays happy).
import { fmtShort } from '../../tz.js';

// Status-cell copy (E10). Derived from derivePhase(...).state; new chrome strings, listed in the deviations register.
export const STATUS_LABELS = {
  voting_open: 'Voting Open',
  apply_open: 'Applications Open',
  voting_soon: 'Not Started',
  voting_closed: 'Closed',
};

// Second line of the header status cell (live). `info` = derivePhase(...), `left` = formatted countdown or null.
// Countdown wins while there is one; an open vote shows when it closes; otherwise nothing.
const COUNTDOWN_SHORT = { 'Applications close in': 'Apps close in', 'Voting opens in': 'Opens in' };
export function statusDetail(info, left, status) {
  if (!info) return '';
  if (left && info.countdownLabel) {
    // More than a day away: the seconds are noise and cost header width on phones ("2d 03h 04m 05s" -> "2d 03h 04m").
    const shown = /^\d+d /.test(left) ? left.replace(/ \d+s$/, '') : left;
    return `${COUNTDOWN_SHORT[info.countdownLabel] || info.countdownLabel} ${shown}`;
  }
  if (info.state === 'voting_open' && status?.voting_closes_at) {
    const when = fmtShort(status.voting_closes_at, info.tz);
    return when ? `Closes ${when}` : '';
  }
  return '';
}

/** "Kyambogo Engineering Society" -> "KES" (max 3 letters). Falls back to "EP" (Election Portal). */
export function initials(name) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return 'EP';
  return words.slice(0, 3).map((w) => w[0].toUpperCase()).join('');
}

// Class hooks handed to default components (they must not contain any `bp-` literal themselves: gate G1).
export const cls = {
  card: 'bp-card', in: 'bp-in', btn: 'bp-btn', ghost: 'bp-btn bp-ghost', sm: 'bp-btn bp-ghost bp-sm', lnk: 'bp-lnk',
  danger: 'bp-btn bp-danger', row2: 'bp-row2', block: 'bp-block',
  // apply form (BP-T6)
  apply: 'bp-apply', lbl: 'bp-lbl', count: 'bp-mu bp-count', sec: 'bp-sec', ta: 'bp-in bp-ta', mu: 'bp-mu', lim: 'bp-lim', upload: 'bp-upload', upEmpty: 'bp-up-empty',
  ban: 'bp-ban', warnBan: 'bp-ban bp-warn', accBan: 'bp-ban bp-acc', alt: 'bp-alt', fee: 'bp-fee', inl: 'bp-lnk bp-inl',
  opt: 'bp-cand bp-opt', on: 'bp-on', del: 'bp-btn bp-ghost bp-sm bp-del', stat: 'bp-upstat', done: 'bp-done',
};

// Phase state -> banner variant (E2): ok / warn / accent / muted, same construction (10% tint + 4 px left border).
export const PHASE_VARIANT = { voting_open: '', voting_soon: ' bp-warn', apply_open: ' bp-acc', voting_closed: ' bp-mute' };

// Console role names for the header subtitle / flat-dashboard crumb group (BP-T7a). Keyed by App's `view` values.
export const ROLE_LABELS = {
  superadmin: 'Super Admin',
  commission: 'Commission',
  it_admin: 'IT Admin',
  financial_controller: 'Financial Controller',
  overseer: 'Overseer',
  vetting: 'Vetting Panel',
};

/** Plain text of a React node (tab labels are JSX fragments like <>Security &amp; SMS</>). Used for the crumb and aria labels. */
export function textOf(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  return textOf(node.props?.children);
}

// One shared status -> pill tone map for the console tables and lists (BP-T8). Statuses are the backend's own words, any case.
const TONES = {
  ok: ['approved', 'force_approved', 'paid', 'active', 'cleared', 'voted', 'certified', 'accepted', 'open'],
  warn: ['pending', 'vetting', 'awaiting', 'idle', 'processing', 'review'],
  neg: ['denied', 'force_denied', 'rejected', 'failed', 'expired', 'locked'],
  mute: ['removed', 'cancelled', 'unpaid', 'none', 'closed'],
};
export function statusTone(status) {
  const s = String(status || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  for (const [tone, list] of Object.entries(TONES)) if (list.includes(s)) return tone;
  return 'mute';
}
