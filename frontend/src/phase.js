import { DEFAULT_TZ, fmtZoned, parseUtc } from './tz';

// Which single notice the voter card shows. Pure, so it can be tested as a table.
// Phase values come from /election-status: 'open' | 'not_started' | 'ended'.
// Applications open takes priority for the banner while voting has not opened.
export const PHASE_STATES = ['apply_open', 'voting_soon', 'voting_open', 'voting_closed'];

/** status (from /election-status) -> { state, tz, dates, countdownTo, countdownLabel } or null when unknown.
 *  `now` (ms) lets an open applications window flip to "closed" the moment its end time passes,
 *  without waiting for the next status refetch. */
export function derivePhase(status, now = Date.now()) {
  if (!status) return null;
  const tz = status.timezone || DEFAULT_TZ;
  const voting = status.voting_phase;
  const apps = status.applications_phase;
  const masterOff = status.is_open === false;

  const appsCloseAt = status.applications_closes_at || null;
  const appsCloseMs = appsCloseAt && parseUtc(appsCloseAt) ? parseUtc(appsCloseAt).getTime() : null;
  const appsOpen = apps === 'open' && !(appsCloseMs != null && appsCloseMs <= now);

  let state;
  if (voting === 'ended' || masterOff) state = 'voting_closed';
  else if (voting === 'not_started') state = appsOpen ? 'apply_open' : 'voting_soon';
  else if (voting === 'open') state = 'voting_open';
  else return null; // unknown shape (old server): show nothing rather than guess

  const votingOpensAt = status.voting_opens_at || null;
  const dates = {
    votingOpensAt: fmtOrNull(votingOpensAt, tz),
    votingClosesAt: fmtOrNull(status.voting_closes_at, tz),
    applicationsCloseAt: fmtOrNull(appsCloseAt, tz),
  };
  // Countdown only for the next upcoming milestone: while applications are open, their closing;
  // once they are closed, voting opening. Never for open/closed voting.
  let countdownTo = null;
  let countdownLabel = null;
  if (state === 'apply_open') {
    if (appsCloseMs != null) { countdownTo = appsCloseAt; countdownLabel = 'Applications close in'; }
    else if (votingOpensAt) { countdownTo = votingOpensAt; countdownLabel = 'Voting opens in'; }
  } else if (state === 'voting_soon' && votingOpensAt) {
    countdownTo = votingOpensAt; countdownLabel = 'Voting opens in';
  }
  const appsClosed = apps === 'ended' || (apps === 'open' && !appsOpen);
  return { state, tz, dates, countdownTo, countdownLabel, appsClosed };
}

function fmtOrNull(v, tz) {
  return v && parseUtc(v) ? fmtZoned(v, tz) : null;
}

/** Milliseconds left -> "2d 03h 04m 05s" (days dropped when 0). Null when already passed. */
export function formatCountdown(ms) {
  if (ms == null || ms <= 0) return null;
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const p = (n) => String(n).padStart(2, '0');
  return `${d > 0 ? `${d}d ` : ''}${p(h)}h ${p(m)}m ${p(s % 60)}s`;
}
