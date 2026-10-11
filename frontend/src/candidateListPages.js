// Official List of Candidates: how the names are split across A4 pages. Pure, so it can be tested without a browser.
// Every page carries the same footer (QR, id, issue time), so each page has to leave room for it: capacity is counted
// in text lines. A position heading costs 2 lines (title + gap), a name costs 1. The first page also carries the full
// header (logo, organisation name, title), so it holds fewer.
export const FIRST_PAGE_LINES = 17;
export const NEXT_PAGE_LINES = 22;

// A name or position title that is too long for one line wraps, and a wrapped line is as tall as any other, so
// capacity counts it as several. Characters per line are deliberately low (wide capitals, the formal template's
// numbering and indent) so the footer, with the QR, can never be pushed off the sheet. Short names cost 1, exactly as before.
export const NAME_CHARS_PER_LINE = 48;
export const HEADING_CHARS_PER_LINE = 36;
const wraps = (text, per) => Math.max(1, Math.ceil(String(text || '').length / per));
export const nameLines = (name) => wraps(name, NAME_CHARS_PER_LINE);
export const headingLines = (position, continued = false) =>
  1 + wraps(`${position || ''}${continued ? ' (continued)' : ''}`, HEADING_CHARS_PER_LINE);

// sections: [{ position, names: [..] }]  ->  pages: [[{ position, continued, startIndex, names }]]
// A position never starts at the very bottom of a page with no name under it; one that is split carries
// "(continued)" and keeps its numbering via startIndex.
export function paginate(sections, first = FIRST_PAGE_LINES, rest = NEXT_PAGE_LINES) {
  const pages = [[]];
  let used = 0;
  const capacity = () => (pages.length === 1 ? first : rest);
  const nextPage = () => { pages.push([]); used = 0; };
  for (const s of sections || []) {
    const remaining = [...(s.names || [])];
    let continued = false;
    let startIndex = 0;
    while (remaining.length) {
      const heading = headingLines(s.position, continued);
      // Not even the heading and the next name fit under what is already on this page: start a new page.
      if (used > 0 && used + heading + nameLines(remaining[0]) > capacity()) nextPage();
      const take = [];
      let cost = heading;
      while (remaining.length) {
        const c = nameLines(remaining[0]);
        // Always take at least one name, so an oversized name can never loop forever.
        if (take.length && used + cost + c > capacity()) break;
        cost += c;
        take.push(remaining.shift());
      }
      pages[pages.length - 1].push({ position: s.position, continued, startIndex, names: take });
      used += cost;
      startIndex += take.length;
      continued = true;
      if (remaining.length) nextPage();
    }
  }
  return pages;
}

export const PAGE_W = 794;   // A4 at 96 dpi
export const PAGE_H = 1123;

export const fmtStamp = (d) => {
  try {
    return new Date(d).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
};
