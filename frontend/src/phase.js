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
  else if (voting === 'open') {
    // Voting has no schedule of its own (so it is "open" only because the master switch is on) while the
    // Applications window on the Timeline is live: the election is in its application stage. A scheduled
    // voting window keeps its own say.
    // `now` flips it back the second the applications deadline passes, without waiting for a refetch.
    const appsLive = status.applications_active && !(appsCloseMs != null && appsCloseMs <= now);
    state = appsLive && !status.voting_scheduled ? 'apply_open' : 'voting_open';
  }
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
  const byElection = status.round_kind === 'by_election' ? {
    position: status.by_election_position || '',
    scheduled: status.by_election_scheduled !== false,
    round1Only: status.by_election_eligibility === 'round1_voters',
  } : null;
  return { state, tz, dates, countdownTo, countdownLabel, appsClosed, byElection };
}

/** Name for the public Results tab, so it never says "Live" for an election whose votes are hidden. */
export function resultsTabLabel(status) {
  const mode = status?.public_results_mode;
  if (!mode) return 'Live Results';                       // old server / unknown: keep the old name
  const state = derivePhase(status)?.state;
  if (status.is_certified) return 'Official Results';
  // Votes are withheld (not live, or not yet released): the page still carries turnout and the voter roll.
  if (mode === 'certified') return 'Turnout & Roll';
  if (state === 'voting_closed') return 'Provisional Results';
  return mode === 'live' && state === 'voting_open' ? 'Live Results' : mode === 'live' ? 'Results' : 'Turnout & Roll';
}

/** Which header buttons apply right now. Vote Now never changes. Apply shows while applications are open; once they
 *  are closed AND vetting is finished, its slot becomes "Candidate List" until voting opens (Help drops its ballot-preview entry only meanwhile). Results shows from voting onward. */
export function navModel(status, now = Date.now()) {
  const ph = derivePhase(status);
  if (!ph) return { resultsLabel: 'Live Results', showApply: true, candidateList: false, showResults: true };
  const vetCloseMs = status.vetting_closes_at && parseUtc(status.vetting_closes_at) ? parseUtc(status.vetting_closes_at).getTime() : null;
  const vettingDone = status.vetting_phase === 'ended' || (vetCloseMs != null && vetCloseMs <= now);
  return {
    resultsLabel: resultsTabLabel(status),
    showApply: !ph.appsClosed,
    candidateList: ph.appsClosed && vettingDone && ph.state === 'voting_soon',   // button: only between vetting and voting
    showResults: ph.state === 'voting_open' || ph.state === 'voting_closed',      // Results tab: voting and beyond
  };
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
