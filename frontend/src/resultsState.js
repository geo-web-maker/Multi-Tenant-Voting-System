// Which "state" the public Results page is in (guide 4.2 / WP-7d).
//
//   not_started  voting has not opened yet -> "Voting opens <date>..." and no turnout / roll
//   embargoed    voting has begun but the server is withholding per-candidate numbers
//   no_votes     nothing has been cast yet (voting open or already closed)
//   live         voting is open and at least one ballot is in
//   closed       voting is over and there are ballots to show
//
// Pure: takes the /election-status and /election-results payloads and returns one of the strings above.

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

/**
 * @param {{is_open?: boolean, voting_phase?: string}} status   /election-status payload
 * @param {{voter_turnout?: number, results?: Array<{votes?: number}>, results_released?: boolean}} results  /election-results payload
 * @returns {'not_started'|'embargoed'|'no_votes'|'live'|'closed'}
 */
export function resultsState(status, results) {
  const s = status || {};
  const r = results || {};
  const isOpen = Boolean(s.is_open);

  if (s.voting_phase === 'not_started' && !isOpen) return 'not_started';
  if (r.results_released === false) return 'embargoed';

  const turnout = num(r.voter_turnout);
  const candidateVotes = (Array.isArray(r.results) ? r.results : []).reduce((sum, c) => sum + num(c?.votes), 0);
  if (turnout <= 0 && candidateVotes <= 0) return 'no_votes';

  return isOpen ? 'live' : 'closed';
}

/** "Voting opens 12 Jan 2026, 08:00 EAT. Results will appear here live." (date part dropped if unknown). */
export function notStartedMessage(opensAtText) {
  const when = opensAtText && opensAtText !== '—' ? ` ${opensAtText}` : ' soon';
  return `Voting opens${when}. Results will appear here live.`;
}
