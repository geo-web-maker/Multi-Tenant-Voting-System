// Official List of Candidates: how the names are split across A4 pages. Pure, so it can be tested without a browser.
// Every page carries the same footer (QR, id, issue time), so each page has to leave room for it. Capacity is counted
// in pixels on the 794 x 1123 sheet, from heights measured in a real print (a name line 26 px, a position heading
// about 21 px, 14 px between positions) with a safety margin of about 10%: the first page also carries the full
// header (logo, organisation name, title), and a long organisation name wraps and makes it taller.
export const NAME_PX = 27;
export const HEADING_PX = 36;        // heading line + the gap under the position block
export const WRAP_PX = 18;           // each extra line of a heading that wraps
export const FIRST_PAGE_PX = 620;
export const NEXT_PAGE_PX = 715;

// A name or position title that is too long for one line wraps and takes more room. Characters per line are
// deliberately low (wide capitals, the formal template's numbering and indent) so the footer, with the QR, can never
// be pushed off the sheet. Short names cost one line.
export const NAME_CHARS_PER_LINE = 48;
export const HEADING_CHARS_PER_LINE = 36;
const wraps = (text, per) => Math.max(1, Math.ceil(String(text || '').length / per));
export const nameCost = (name) => NAME_PX * wraps(name, NAME_CHARS_PER_LINE);
export const headingCost = (position, continued = false) =>
  HEADING_PX + WRAP_PX * (wraps(`${position || ''}${continued ? ' (continued)' : ''}`, HEADING_CHARS_PER_LINE) - 1);
export const pageCost = (page) => page.reduce((n, x) => n + headingCost(x.position, x.continued) + x.names.reduce((m, nm) => m + nameCost(nm), 0), 0);

// sections: [{ position, names: [..] }]  ->  pages: [[{ position, continued, startIndex, names }]]
// A position never starts at the very bottom of a page with no name under it; one that is split carries
// "(continued)" and keeps its numbering via startIndex.
export function paginate(sections, first = FIRST_PAGE_PX, rest = NEXT_PAGE_PX) {
  const pages = [[]];
  let used = 0;
  const capacity = () => (pages.length === 1 ? first : rest);
  const nextPage = () => { pages.push([]); used = 0; };
  for (const s of sections || []) {
    const remaining = [...(s.names || [])];
    let continued = false;
    let startIndex = 0;
    while (remaining.length) {
      const heading = headingCost(s.position, continued);
      // Not even the heading and the next name fit under what is already on this page: start a new page.
      if (used > 0 && used + heading + nameCost(remaining[0]) > capacity()) nextPage();
      const take = [];
      let cost = heading;
      while (remaining.length) {
        const c = nameCost(remaining[0]);
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
