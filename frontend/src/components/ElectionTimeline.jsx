import React from 'react';
import api from '../api';
import { DEFAULT_TZ, tzShort, utcOffsetLabel } from '../tz';

// "Today" is always the day it is in the ELECTION timezone (set on the
// admin Timeline), never the viewer's device timezone — a voter abroad sees
// the same live day/time the election itself runs on.
function zonedToday(now, tz) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now).map(x => [x.type, x.value]));
  return { year: +p.year, month: +p.month - 1, day: +p.day };
}

// --- Date-range extraction from free text (e.g. "Thu 24th Sept & Fri 25th
// Sept", "22 - 24 September", "Mon 6th Oct"). There's no separate structured
// date field on a milestone — the printed label IS the date range, so
// "today" is derived by pulling every day/month token out of the text and
// checking whether any of them is today. Ambiguous labels with no day+month
// pair (e.g. a bare "Tue, Wed, Thu, Fri and Sat" weekday list) simply never
// match — that's the same as "no date," not an error.

const MONTHS = {
  jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2, apr: 3, april: 3,
  may: 4, jun: 5, june: 5, jul: 6, july: 6, aug: 7, august: 7,
  sep: 8, sept: 8, september: 8, oct: 9, october: 9, nov: 10, november: 10,
  dec: 11, december: 11,
};

const ORD = '(?:st|nd|rd|th)?';
const SEP = '\\s*(?:-|–|—|to|until)\\s*';
// Two separate passes (day-first, month-first) rather than one alternation:
// with a single combined regex, "Thu 24th Sept" is eaten as month="Thu",
// day=24 and the real "24th Sept" is never seen. Each pass takes an optional
// range ("22 - 24 September", "Sept 22-24") and expands it to every day.
const DAY_FIRST_RE = new RegExp(
  `\\b(\\d{1,2})${ORD}(?:${SEP}(\\d{1,2})${ORD})?\\s+([A-Za-z]{3,9})\\b`, 'gi');
const MONTH_FIRST_RE = new RegExp(
  `\\b([A-Za-z]{3,9})\\s+(\\d{1,2})${ORD}(?:${SEP}(\\d{1,2})${ORD})?\\b`, 'gi');

function monthIndex(word) {
  return MONTHS[word.toLowerCase()];
}

/** Extracts every {month, day} pair found in free text (ranges expanded),
 * ignoring words that aren't real month names ("Thu", "Fri", …). */
function extractDaysAndMonths(label) {
  if (!label) return [];
  const found = [];
  const seen = new Set();
  const push = (month, from, to) => {
    const end = to == null ? from : to;
    if (end < from || end - from > 31) return;
    for (let day = from; day <= end; day++) {
      if (day < 1 || day > 31) continue;
      const key = `${month}-${day}`;
      if (!seen.has(key)) { seen.add(key); found.push({ month, day }); }
    }
  };
  let m;
  DAY_FIRST_RE.lastIndex = 0;
  while ((m = DAY_FIRST_RE.exec(label))) {
    const month = monthIndex(m[3]);
    if (month !== undefined) push(month, parseInt(m[1], 10), m[2] ? parseInt(m[2], 10) : null);
  }
  MONTH_FIRST_RE.lastIndex = 0;
  while ((m = MONTH_FIRST_RE.exec(label))) {
    const month = monthIndex(m[1]);
    if (month !== undefined) push(month, parseInt(m[2], 10), m[3] ? parseInt(m[3], 10) : null);
  }
  return found;
}

/** True if any day/month extracted from the label matches today's month
 * and day (`today` = zonedToday()), in the current year. */
function labelMatchesToday(label, today) {
  return extractDaysAndMonths(label).some(
    ({ month, day }) => month === today.month && day === today.day
  );
}

// --- Automatic week numbering -------------------------------------------
// Week labels are never typed in. They're derived from the dates parsed out
// of each row's picked start/end dates (or, for older text-only rows, the
// dates read from date_label), using a hybrid of "relative to the first event"
// and "calendar weeks":
//   • Week 1 begins on the EARLIEST event date across the roadmap, even if
//     that falls mid-week.
//   • Week 1 runs up to the day before the next `weekStartDay` (0 = Sunday …
//     6 = Saturday, admin-configurable), which starts Week 2. Every later
//     week is a normal 7-day block beginning on that weekday.
// A range row is placed by its start date. Rows with no parseable date inherit the previous row's
// week rather than getting a label of their own. Row order is never changed.

const DAY_MS = 86_400_000;

// UTC-midnight day number, so DST shifts can never nudge a date across a
// day boundary during the arithmetic below.
const dayNum = (y, m, d) => Math.floor(Date.UTC(y, m, d) / DAY_MS);

/** Earliest {month, day} in a label resolved to a day number. The roadmap has
 * no year, so it's assumed to be `refYear`, rolling forward a year whenever
 * a row would otherwise land far before the previous one (Dec → Jan). */
function firstDateNum(label, refYear, prev) {
  const found = extractDaysAndMonths(label);
  if (!found.length) return null;
  const nums = found.map(({ month, day }) => {
    let year = refYear;
    let n = dayNum(year, month, day);
    while (prev != null && n < prev - 180) { year += 1; n = dayNum(year, month, day); }
    return n;
  });
  return Math.min(...nums);
}

const parseISO = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return dayNum(y, m - 1, d);
};

/** Resolves a milestone to { startNum, endNum, label }. Rows saved with the
 * date picker carry exact ISO start_date / end_date; older free-text rows
 * (date_label only) fall back to reading day/month out of the text. */
function rowDates(m, refYear, prev) {
  if (m.start_date) {
    const startNum = parseISO(m.start_date);
    const endNum = m.end_date ? parseISO(m.end_date) : startNum;
    return { startNum, endNum, label: formatRange(startNum, endNum) };
  }
  const n = firstDateNum(m.date_label, refYear, prev);
  return { startNum: n, endNum: n, label: m.date_label, legacy: true };
}

const dayPart = (n, o) => new Date(n * DAY_MS).toLocaleDateString('en-GB', { timeZone: 'UTC', ...o });
const fmtDay = (n, withMonth = true) =>
  `${dayPart(n, { weekday: 'short' })} ${dayPart(n, { day: 'numeric' })}${withMonth ? ' ' + dayPart(n, { month: 'short' }) : ''}`;

function formatRange(startNum, endNum) {
  if (endNum === startNum) return fmtDay(startNum);
  const s = new Date(startNum * DAY_MS), e = new Date(endNum * DAY_MS);
  const sameMonth = s.getUTCMonth() === e.getUTCMonth() && s.getUTCFullYear() === e.getUTCFullYear();
  return `${fmtDay(startNum, !sameMonth)} – ${fmtDay(endNum)}`;
}

/** True when today falls on any day of the row (start..end inclusive). */
function rowIsToday(m, info, today) {
  if (!info.legacy) {
    const t = dayNum(today.year, today.month, today.day);
    return t >= info.startNum && t <= info.endNum;
  }
  return labelMatchesToday(m.date_label, today);
}

function groupByWeek(milestones, weekStartDay = 1, refYear = new Date().getFullYear()) {
  // Pass 1: one day number (or null) per row, in row order.
  let prev = null;
  const infos = milestones.map(m => {
    const info = rowDates(m, refYear, prev);
    if (info.startNum != null) prev = info.startNum;
    return info;
  });
  const nums = infos.map(i => i.startNum);
  const known = nums.filter(n => n != null);

  // Week 2 starts on the first `weekStartDay` strictly after the earliest event.
  let week2Start = null;
  if (known.length) {
    const first = Math.min(...known);
    const firstDow = new Date(first * DAY_MS).getUTCDay();
    const daysToNext = ((weekStartDay - firstDow + 7) % 7) || 7;
    week2Start = first + daysToNext;
  }
  const weekOf = n => (n < week2Start ? 1 : 2 + Math.floor((n - week2Start) / 7));

  // Pass 2: group consecutive rows sharing a week number.
  const groups = [];
  let current = null;
  let lastWeek = null;
  milestones.forEach((m, i) => {
    const w = nums[i] != null ? weekOf(nums[i]) : lastWeek; // undated → inherit
    if (!current || w !== current.weekNo) {
      current = { weekNo: w, week: w != null ? `Week ${w}` : '', rows: [] };
      groups.push(current);
    }
    if (w != null) lastWeek = w;
    current.rows.push({ m, info: infos[i] });
  });
  return groups;
}

/**
 * Voter-facing Election Timeline: a live clock (in the election timezone) and
 * the informational, auto-weeked milestone roadmap from /election-roadmap.
 * The 4 enforced phases (applications / campaign / voting / results) are
 * intentionally NOT shown here — they're an admin-side view of when the
 * system switches state (Timeline tab), not something voters need.
 */
export default function ElectionTimeline() {
  const [milestones, setMilestones] = React.useState(null); // null = loading, [] once loaded
  const [milestonesError, setMilestonesError] = React.useState(false);
  const [weekStartDay, setWeekStartDay] = React.useState(1); // 0 = Sunday … 6 = Saturday
  const [timezone, setTimezone] = React.useState(DEFAULT_TZ);

  React.useEffect(() => {
    api.get('/election-roadmap')
      .then(res => {
        setMilestones(res.data.milestones || []);
        if (Number.isInteger(res.data.week_start_day)) setWeekStartDay(res.data.week_start_day);
        if (res.data.timezone) setTimezone(res.data.timezone);
      })
      .catch(() => setMilestonesError(true));
  }, []);

  // One shared clock, ticking every second: drives the live date/time
  // header, and keeps the highlighted "today" row correct across
  // midnight without a refresh.
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Everything is read in the election timezone set on the admin Timeline.
  const tz = timezone;
  const today = zonedToday(now, tz);
  const weeks = groupByWeek(milestones || [], weekStartDay, today.year);

  return (
    <div>
      <style>{PULSE_CSS}</style>
      <LiveClock now={now} tz={tz} />
      {milestonesError && <p style={{ fontSize: 13, opacity: 0.7 }}>Couldn't load the election roadmap.</p>}
      {!milestonesError && !milestones && <p style={{ fontSize: 13, opacity: 0.7 }}>Loading…</p>}
      {milestones && milestones.length === 0 && <p style={{ fontSize: 13, opacity: 0.7 }}>No roadmap has been published yet.</p>}
      {weeks.length > 0 && (
        <div>
          {weeks.map(({ week, rows }, gi) => (
            <div key={gi} style={{ marginBottom: 16 }}>
              {week && <h4 style={weekHeaderStyle}>{week}</h4>}
              {rows.map(({ m, info }, i) => {
                const isToday = rowIsToday(m, info, today);
                return (
                  <div key={i} style={milestoneRowStyle(isToday)}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>
                      {info.label}
                      {isToday && <span className="et-pulse" style={pulseDotStyle} title="Today" />}
                    </div>
                    {m.activities && m.activities.length > 0 && (
                      <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 13 }}>
                        {m.activities.map((a, j) => <li key={j}>{a}</li>)}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const PULSE_CSS = `
@keyframes et-pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--brand-accent) 60%, transparent); }
  70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
.et-pulse { animation: et-pulse 1.8s ease-out infinite; }
@media (prefers-reduced-motion: reduce) { .et-pulse { animation: none; } }
`;

const pulseDotStyle = {
  display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
  background: 'var(--brand-accent)', marginLeft: 8, verticalAlign: 'middle',
};

/** Live date + time header, in the election timezone (not the device's). */
function LiveClock({ now, tz }) {
  const date = new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }).format(now).replace(',', '');
  const time = new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(now);
  return (
    <div style={clockBoxStyle} role="timer" aria-label={`${date}, ${time}, ${tzShort(tz, now)}`}>
      <div style={{ fontSize: 12, fontWeight: 600, opacity: 0.75 }}>{date}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 2 }}>
        <span style={{ fontSize: 28, fontWeight: 700, fontVariantNumeric: 'tabular-nums', letterSpacing: '0.02em' }}>{time}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--brand-accent)' }}>{tzShort(tz, now)}</span>
      </div>
      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 2 }}>
        Election time · {utcOffsetLabel(tz, now)} · {tz.replace(/_/g, ' ')}
      </div>
    </div>
  );
}

const clockBoxStyle = {
  padding: '10px 14px', marginBottom: 16, borderRadius: 10,
  border: '1px solid var(--border-color)',
  borderLeft: '3px solid var(--brand-accent)',
  backgroundColor: 'color-mix(in srgb, var(--brand-accent) 8%, transparent)',
};

const weekHeaderStyle = {
  fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
  opacity: 0.7, margin: '0 0 6px',
};

function milestoneRowStyle(today) {
  return {
    padding: '8px 10px', borderRadius: 8, marginBottom: 4,
    border: today ? '1px solid var(--brand-accent)' : '1px solid transparent',
    backgroundColor: today ? 'color-mix(in srgb, var(--brand-accent) 12%, transparent)' : 'transparent',
  };
}
