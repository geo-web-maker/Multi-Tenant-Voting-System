// D2c (WP-9.1): plain-language sentences from the analytics summary. Pure.
// Rules: a sentence is skipped (never guessed) when its denominator is zero or a field is missing, so no "NaN%"
// and no divide-by-zero; only counts and page/element/reason labels are used, never ids or names.
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const pctOf = (part, whole) => {
  const p = num(part), w = num(whole);
  if (p === null || w === null || w <= 0) return null;
  return `${Math.round((p / w) * 100)}%`;
};
const plain = (label) => String(label ?? '').replace(/_+/g, ' ').trim(); // codes use _; element names keep their -
const secs = (ms) => `${(ms / 1000).toFixed(1)} s`;
const step = (steps, key) => (Array.isArray(steps) ? steps.find((s) => s?.key === key)?.value : undefined);

export function buildInsights(summary) {
  const s = summary || {};
  const out = [];

  // 1. Voter login -> application form
  const voters = num(step(s.funnels?.voting?.steps, 'identity_page'));
  const applyOpened = num(step(s.funnels?.apply?.steps, 'form_page'));
  const ratio = pctOf(applyOpened, voters);
  if (ratio !== null && applyOpened > 0) {
    out.push(`The application form was opened in ${applyOpened} sessions, ${ratio} of the ${voters} sessions that opened the voter login.`);
  }

  // 2. Identity failures + top reason
  const id = s.funnels?.voting?.identity;
  const failedShare = pctOf(id?.failed, id?.attempts);
  if (failedShare !== null && id.failed > 0) {
    const top = Array.isArray(id.reasons) ? id.reasons.find((r) => r && num(r.value) > 0) : null;
    out.push(`${id.failed} of ${id.attempts} identity checks failed (${failedShare})${top ? `. Most common reason: ${plain(top.label)}` : ''}.`);
  }

  // 3. 3G / unknown network share + slowest loads
  const nets = Array.isArray(s.network) ? s.network.filter((n) => n && ['3g', 'unknown'].includes(String(n.label).toLowerCase())) : [];
  const total = Array.isArray(s.network) ? s.network.reduce((a, n) => a + (num(n?.value) || 0), 0) : 0;
  const slowShare = pctOf(nets.reduce((a, n) => a + (num(n.value) || 0), 0), total);
  if (slowShare !== null && nets.some((n) => num(n.value) > 0)) {
    const p95s = (Array.isArray(s.network_perf) ? s.network_perf : [])
      .filter((r) => ['3g', 'unknown'].includes(String(r?.net).toLowerCase()) && num(r.load_p95) !== null).map((r) => r.load_p95);
    out.push(`${slowShare} of sessions are on 3G or an unknown network${p95s.length ? `; their slowest loads take up to ${secs(Math.max(...p95s))}` : ''}.`);
  }

  // 4. Dead clicks
  const dead = Array.isArray(s.friction?.dead_by_element) ? s.friction.dead_by_element.find((d) => d && num(d.value) > 0) : null;
  if (dead) out.push(`Most dead clicks (taps that did nothing): "${plain(dead.label)}" on the ${plain(dead.page)} page, ${dead.value} times.`);

  // 5. Opened vs submitted
  const submitted = num(s.funnels?.apply?.submit?.ok);
  if (applyOpened !== null && applyOpened > 0 && submitted !== null) {
    out.push(`${applyOpened} sessions opened the application form and ${submitted} applications were submitted.`);
  }
  return out;
}
