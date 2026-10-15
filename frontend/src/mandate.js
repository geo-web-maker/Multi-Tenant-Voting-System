// Unopposed-candidate rule: how many valid votes a lone candidate needs to be declared elected.
// One place for the maths so the public results page, the printed report and the signed report always agree.
// `src` is any payload carrying the server fields (/election-results or /admin/official-report).
const fmtPct = (n) => String(Number(n.toFixed(2)));
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

export function unopposedRule(src = {}) {
  const rule = src.unopposed_rule || 'votes';
  const minVotes = Math.max(1, Math.floor(Number(src.unopposed_min_votes)) || 100);
  const turnout = Number(src.voter_turnout) || 0;
  const registered = Number(src.registered_voters) || 0;
  const pctOf = (pct, base) => Math.max(1, Math.ceil(Number((pct * base / 100).toFixed(6))));

  if (rule === 'pct_voted') {
    const pct = Number(src.unopposed_pct_voted);
    if (pct > 0) {
      const required = pctOf(pct, turnout);
      return { rule, required, text: `${fmtPct(pct)}% of the voters who voted (${plural(required, 'vote')} at the current turnout of ${turnout})` };
    }
  }
  if (rule === 'pct_registered' && registered > 0) {
    const pct = Number(src.unopposed_pct_registered);
    if (pct > 0) {
      const required = pctOf(pct, registered);
      return { rule, required, text: `${fmtPct(pct)}% of registered voters (${plural(required, 'vote')} out of ${registered} registered)` };
    }
  }
  return { rule: 'votes', required: minVotes, text: `${plural(minVotes, 'valid vote')}` };
}
