// Estimated cost of voter-code SMS under a first-send / resend provider split.
// Shares are the EgoSMS percentage (0-100); MamboSMS gets the rest.

const clampPct = (v) => Math.min(100, Math.max(0, Number.isFinite(Number(v)) ? Number(v) : 0));

/**
 * @param {object} o
 * @param {number} o.voters           voters who will each get a first code
 * @param {number} o.resendsPerVoter  average resends per voter (0.5 = one resend for every two voters)
 * @param {number} o.parts            SMS parts per code (usually 1)
 * @param {number} o.firstEgoPct      share of first codes sent through EgoSMS
 * @param {number} o.resendEgoPct     share of resends sent through EgoSMS
 * @param {{egosms:number|null, mambosms:number|null}} o.costPerPart  UGX per part, null = not set
 */
export function estimateOtpCost({ voters, resendsPerVoter, parts = 1, firstEgoPct, resendEgoPct, costPerPart }) {
  const n = Math.max(0, Number(voters) || 0);
  const firsts = n;
  const resends = n * Math.max(0, Number(resendsPerVoter) || 0);
  const p = Math.max(1, Number(parts) || 1);
  const f = clampPct(firstEgoPct) / 100;
  const r = clampPct(resendEgoPct) / 100;
  const msgs = {
    egosms: (firsts * f + resends * r) * p,
    mambosms: (firsts * (1 - f) + resends * (1 - r)) * p,
  };
  const ego = costPerPart?.egosms;
  const mambo = costPerPart?.mambosms;
  // A provider that carries messages but has no price makes the total unknown; never show a partial total as complete.
  const missing = [];
  if (msgs.egosms > 0 && (ego == null || ego === '')) missing.push('egosms');
  if (msgs.mambosms > 0 && (mambo == null || mambo === '')) missing.push('mambosms');
  const cost = (m, c) => (m > 0 && c != null && c !== '' ? m * Number(c) : 0);
  const byProvider = { egosms: cost(msgs.egosms, ego), mambosms: cost(msgs.mambosms, mambo) };
  return {
    firsts, resends: Math.round(resends), messages: { egosms: Math.round(msgs.egosms), mambosms: Math.round(msgs.mambosms) },
    byProvider, total: missing.length ? null : byProvider.egosms + byProvider.mambosms, missing,
  };
}
