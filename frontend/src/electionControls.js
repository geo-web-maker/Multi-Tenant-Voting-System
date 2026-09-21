// Shared start/stop logic for the Super Admin and Admin dashboards.
//
// /admin/toggle-election answers 409 {code: 'early_stop_reason_required'} when the election is being
// stopped while an enforced voting window is still live. The server is the single source of truth for
// "is this an early stop?", so the UI asks for the reason only when told to and then retries.
import { fmtZoned } from './tz';

const MIN_REASON = 5;

/**
 * Ask for the reason the server demanded (early stop / early end of a live voting window).
 * `d` is the 409 `detail` object. Resolves the trimmed reason, or null if the admin cancelled.
 */
export async function askEarlyReason(d, prompt, lead, confirmText = 'Confirm') {
  const ends = d.voting_ends_at ? fmtZoned(d.voting_ends_at, d.timezone) : null;
  const ask = (msg) => prompt(`${msg}\n\nReason (recorded in the audit log):`, {
    placeholder: 'e.g. Suspected ballot tampering', confirmText,
  });
  let reason = await ask(lead.replace('{ends}', ends || 'its scheduled end'));
  while (reason != null && reason.trim().length < MIN_REASON) {
    reason = await ask(`A reason of at least ${MIN_REASON} characters is required.`);
  }
  return reason == null ? null : reason.trim();
}

/** Returns the server response, or null if the admin cancelled the reason prompt. Throws on other errors. */
export async function toggleElection(api, prompt) {
  const post = (body) => api.post('/admin/toggle-election', body);
  try {
    return (await post()).data;
  } catch (e) {
    const d = e?.response?.data?.detail;
    if (e?.response?.status !== 409 || d?.code !== 'early_stop_reason_required') throw e;
    const reason = await askEarlyReason(
      d, prompt,
      'The voting window is still open until {ends}.\nStopping now ends voting early for everyone.',
      'Stop election',
    );
    if (reason == null) return null;
    return (await post({ reason })).data;
  }
}

/** { text, kind } for the toast after a successful toggle — says what "started" really means. */
export function electionToggleFeedback(data) {
  if (!data.is_open) {
    return data.early_stop
      ? { text: 'Election stopped early. Your reason has been recorded in the audit log.', kind: 'success' }
      : { text: 'Election is now CLOSED.', kind: 'info' };
  }
  if (data.voting_window_ended) {
    return {
      text: 'Election switched on, but the voting window has already ended, so voting stays closed. '
        + 'Edit the schedule (Timeline tab) or grant an exception to let people vote.',
      kind: 'error',
    };
  }
  if (data.voting_opens_at) {
    return { text: `Election switched on. Voting opens ${fmtZoned(data.voting_opens_at, data.timezone)}.`, kind: 'info' };
  }
  return { text: 'Election is now OPEN.', kind: 'success' };
}
