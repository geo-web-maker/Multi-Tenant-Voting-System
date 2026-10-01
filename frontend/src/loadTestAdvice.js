// Load-test sizing advice for the Site Usage page (guide 5.6d).
//
//   expected_peak = voters x share_in_busiest_hour x (avg_session_seconds / 3600)
//
// i.e. how many people are on the site at the same moment in the busiest hour. Run the load test at
// 1.5x to 2x that figure to leave headroom.

const clean = (n) => (Number.isFinite(Number(n)) && Number(n) > 0 ? Number(n) : 0);

/** Share (0..1) of all activity that falls in the single busiest hour of `hours` (24 counts). */
export function busiestHourShare(hours) {
  const list = Array.isArray(hours) ? hours.map(clean) : [];
  const total = list.reduce((a, b) => a + b, 0);
  return total > 0 ? Math.max(...list) / total : 0;
}

/** @returns {{expected: number, low: number, high: number}} whole numbers; all 0 for missing or invalid input. */
export function loadTestAdvice({ voters, shareBusiestHour, avgSessionSeconds }) {
  const expected = clean(voters) * Math.min(clean(shareBusiestHour), 1) * (clean(avgSessionSeconds) / 3600);
  const round = (x) => Math.round(x * 1e6) / 1e6;
  return {
    expected: Math.round(round(expected)),
    low: Math.ceil(round(expected * 1.5)),
    high: Math.ceil(round(expected * 2)),
  };
}
