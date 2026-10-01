// Time labels and the default range for the Site Usage charts (guide 5.6b, 5.6c).

const pad2 = (n) => String(n).padStart(2, '0');

/**
 * Axis label for one timeline bucket.
 *  - hour buckets are real instants ("2026-09-14T23:00:00Z"): shown as D/M HHh in the election time zone
 *  - day buckets ("2026-09-14") are UTC-day totals, so they keep their plain date (D/M); shifting a
 *    whole-day total into another zone would label it with a day it does not cover.
 */
export function bucketLabel(t, bucket, tz = 'Africa/Kampala') {
  if (typeof t !== 'string' || !t) return '';
  if (bucket !== 'hour' || t.length === 10) {
    const d = new Date(t.length === 10 ? `${t}T00:00:00Z` : t);
    return Number.isNaN(d.getTime()) ? '' : `${d.getUTCDate()}/${d.getUTCMonth() + 1}`;
  }
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return '';
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, day: 'numeric', month: 'numeric', hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(d).map((x) => [x.type, x.value]));
  return `${Number(p.day)}/${Number(p.month)} ${pad2(Number(p.hour))}h`;
}

/**
 * Default "Date range" (in days) for the first load: 1 ("Last 24 hours") when every recorded day is
 * today (UTC), otherwise 7. `trackingSince` is the earliest recorded day, "YYYY-MM-DD" or null.
 */
export function defaultRangeDays(trackingSince, now = new Date()) {
  if (typeof trackingSince !== 'string' || trackingSince.length !== 10) return 7;
  const today = `${now.getUTCFullYear()}-${pad2(now.getUTCMonth() + 1)}-${pad2(now.getUTCDate())}`;
  return trackingSince >= today ? 1 : 7;
}
