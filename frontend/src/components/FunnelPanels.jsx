import React from 'react';
import { BarRows } from './UsageCharts';

const pct = (v) => `${((v || 0) * 100).toFixed(1)}%`;
const ms = (v) => (v === null || v === undefined ? 'n/a' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`);

// Plain-language names for the short reason codes the backend records.
const REASONS = {
  not_on_roll: 'Not on the voter register',
  name_mismatch: 'Name does not match the register',
  already_voted: 'Already voted',
  already_applied: 'Already applied for this position',
  no_phone: 'No phone number on file',
  phone_choice: 'Asked to choose a phone number',
  bad_phone_choice: 'Invalid phone choice',
  sms_failed: 'SMS could not be delivered',
  guess_lock: 'Locked out after wrong codes',
  wrong_code: 'Wrong code entered',
  no_live_code: 'Code expired or not requested',
  budget: 'SMS budget limit reached',
  captcha_required: 'Security check needed or failed',
  closed: 'Election is closed',
  phase_not_open: 'Phase has not opened yet',
  phase_ended: 'Phase has ended',
  phase_closed: 'Phase is closed',
  legacy_cap: 'Legacy send cap reached',
  voter_not_found: 'Voter not found',
  session_expired: 'Voting session expired',
  otp_required: 'Code verification missing',
  ineligible: 'Ineligible voter',
  invalid_candidate: 'Invalid candidate',
  candidate_missing: 'Candidate not found',
  duplicate_pick: 'Duplicate or repeated pick',
  bad_file_type: 'Unsupported image type',
  too_large: 'Image over 5 MB',
  upload_failed: 'Image upload failed',
};
const reasonLabel = (code) => REASONS[code] || (/^http_\d+$/.test(code) ? `HTTP ${code.slice(5)}` : code);

export function FunnelSteps({ steps = [] }) {
  const first = steps.find((s) => s.value > 0)?.value || 0;
  const items = steps.map((s, i) => {
    const prev = i > 0 ? steps[i - 1].value : null;
    let note = s.unit === 'sessions' ? 'sessions' : 'attempts';
    if (first > 0) note += ` · ${pct(s.value / first)} of step 1`;
    if (prev && s.value < prev) note += ` · ${pct(1 - s.value / prev)} lost since previous step`;
    return { label: `${i + 1}. ${s.label}`, value: s.value, note };
  });
  return <BarRows items={items} sub={(x) => x.note} empty="No activity has been recorded for this period." />;
}

// Attempts, successes and the reasons behind the failures for one route.
export function OutcomeBlock({ title, outcome }) {
  if (!outcome) return null;
  const reasons = (outcome.reasons || []).map((r) => ({ label: reasonLabel(r.label), value: r.value }));
  return (
    <div style={{ marginTop: 14 }}>
      <h4 style={h4}>{title}</h4>
      <p style={muted}>
        {outcome.attempts} attempt{outcome.attempts === 1 ? '' : 's'} · {outcome.ok} succeeded · {outcome.failed} did not
        {outcome.attempts ? ` (${pct(outcome.failed / outcome.attempts)} failed)` : ''}
      </p>
      <BarRows items={reasons} empty="No failures recorded." />
    </div>
  );
}

export function ApplyFunnelPanel({ funnel }) {
  if (!funnel) return null;
  return (
    <div style={panel} className="card-pad">
      <h3 style={h3}>Application funnel</h3>
      <p style={muted}>Session steps count distinct visitors; attempt steps count requests, so retries add up.</p>
      <FunnelSteps steps={funnel.steps} />
      <p style={{ ...muted, marginTop: 10 }}>Submit pressed but blocked by an unfilled field: {funnel.blocked_by_form || 0} time(s).</p>
      <OutcomeBlock title="Eligibility check (ID and name)" outcome={funnel.eligibility} />
      <OutcomeBlock title="Image and proof uploads" outcome={funnel.upload} />
      <OutcomeBlock title="Final submission" outcome={funnel.submit} />
    </div>
  );
}

export function VotingFunnelPanel({ funnel }) {
  if (!funnel) return null;
  const quiet = !funnel.steps.some((s) => s.value > 0);
  return (
    <div style={panel} className="card-pad">
      <h3 style={h3}>Voting funnel</h3>
      <p style={muted}>
        {quiet ? 'No voting activity yet. This fills in once voting opens.'
          : `Identity attempts per visitor: ${funnel.attempts_per_session}. Values above 1 mean people are retrying.`}
      </p>
      <FunnelSteps steps={funnel.steps} />
      <OutcomeBlock title="Identity check and code sending" outcome={funnel.identity} />
      <OutcomeBlock title="Code verification" outcome={funnel.otp} />
      <OutcomeBlock title="Vote submission" outcome={funnel.vote} />
    </div>
  );
}

export function FrictionDetail({ friction }) {
  if (!friction) return null;
  const el = (x) => ({ label: `${x.label}`, value: x.value, sub: x.page });
  return (
    <div style={panel} className="card-pad">
      <h3 style={h3}>Friction detail</h3>
      <h4 style={h4}>Dead clicks by element</h4>
      <BarRows items={(friction.dead_by_element || []).map(el)} sub={(x) => `on ${x.sub}`} empty="No dead clicks recorded." />
      <h4 style={h4}>Rage clicks by element</h4>
      <BarRows items={(friction.rage_by_element || []).map(el)} sub={(x) => `on ${x.sub}`} empty="No rage clicks recorded." />
      <h4 style={h4}>Network failures by page and connection type</h4>
      <BarRows items={friction.network_failures} empty="No network failures recorded." />
    </div>
  );
}

export function NetworkPerformance({ rows = [] }) {
  return (
    <div>
      <h4 style={h4}>Performance by connection type</h4>
      {rows.length ? (
        <div className="table-scroll">
          <table style={table}>
            <thead><tr>{['Connection', 'Sessions', 'Load p50', 'Load p95', 'First API p50', 'First API p95', 'Cold'].map((c) => <th key={c} style={th}>{c}</th>)}</tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.net}>
                <td style={td}>{r.net}</td><td style={td}>{r.sessions}</td><td style={td}>{ms(r.load_p50)}</td><td style={td}>{ms(r.load_p95)}</td>
                <td style={td}>{ms(r.first_api_p50)}</td><td style={td}>{ms(r.first_api_p95)}</td><td style={td}>{pct(r.cold_pct)}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      ) : <p style={muted}>No performance samples for this period.</p>}
    </div>
  );
}

export function ChannelsPanel({ channels = [] }) {
  const example = `${typeof window !== 'undefined' ? window.location.origin : ''}/?src=whatsapp`;
  return (
    <div style={panel} className="card-pad">
      <h3 style={h3}>Traffic channels</h3>
      <p style={muted}>
        Add a short tag to each link you share, for example <code>{example}</code>. Use lower-case letters, digits, - or _.
        Untagged visits are not listed here.
      </p>
      <BarRows items={channels} sub={(x) => `Bounce rate ${pct(x.bounce)}`} empty="No tagged visits yet." />
    </div>
  );
}

const panel = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)', minWidth: 0 };
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const h4 = { margin: '14px 0 6px', fontSize: 13, color: 'var(--text-muted)' };
const table = { width: '100%', borderCollapse: 'collapse', fontSize: 13 };
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', whiteSpace: 'nowrap' };
const td = { padding: '6px 8px', borderBottom: '1px solid var(--border-color)' };
