// Election-timezone helpers. The backend stores UTC (naive ISO, no "Z"); admins think and type in the
// ELECTION timezone, which is set on the Timeline and is independent of the browser's timezone — so an
// admin on a laptop set to another zone can't start or end an election at the wrong moment.
export const DEFAULT_TZ = 'Africa/Kampala';
export const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

/** Backend sends naive UTC ("2026-01-10T12:00:00"); `new Date()` would read that as LOCAL time. */
export function parseUtc(v) {
  if (!v) return null;
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
  return Number.isNaN(d.getTime()) ? null : d;
}

function wallParts(ms, tz) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(new Date(ms)).map(x => [x.type, x.value]));
  return p;
}
const offsetMs = (ms, tz) => {
  const p = wallParts(ms, tz);
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - Math.floor(ms / 1000) * 1000;
};

/** UTC value -> "YYYY-MM-DDTHH:mm" wall-clock in `tz`, for <input type="datetime-local">. */
export function utcToZonedInput(v, tz) {
  const d = parseUtc(v);
  if (!d) return '';
  const p = wallParts(d.getTime(), tz);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** Wall-clock typed in `tz` -> UTC ISO string (handles DST by re-checking the offset). */
export function zonedInputToUtcISO(input, tz) {
  if (!input) return null;
  const [d, t] = input.split('T');
  const [y, mo, da] = d.split('-').map(Number);
  const [h, mi] = (t || '00:00').split(':').map(Number);
  const asUtc = Date.UTC(y, mo - 1, da, h, mi);
  let guess = asUtc - offsetMs(asUtc, tz);
  guess = asUtc - offsetMs(guess, tz);
  return new Date(guess).toISOString();
}

export function tzShort(tz, at = new Date()) {
  const n = new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(at).find(x => x.type === 'timeZoneName');
  return n ? n.value : tz;
}
export function utcOffsetLabel(tz, at = new Date()) {
  const m = Math.round(offsetMs(at.getTime(), tz) / 60000);
  const sign = m < 0 ? '-' : '+';
  const a = Math.abs(m);
  return `UTC${sign}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}`;
}

/** "12 Jan 2026, 08:00 EAT" — always in the election timezone. */
export function fmtZoned(v, tz) {
  const d = parseUtc(v);
  if (!d) return '—';
  // NOTE: dateStyle/timeStyle can't be combined with timeZoneName (throws "Invalid option : option"),
  // so use explicit fields instead.
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short',
  }).format(d);
}

export function zoneList() {
  try { return Intl.supportedValuesOf('timeZone'); } catch { /* older browsers */ }
  return ['Africa/Kampala', 'Africa/Nairobi', 'Africa/Lagos', 'Africa/Johannesburg', 'Africa/Cairo', 'Europe/London',
    'Europe/Paris', 'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore', 'America/New_York', 'America/Chicago',
    'America/Los_Angeles', 'Australia/Sydney', 'UTC'];
}
