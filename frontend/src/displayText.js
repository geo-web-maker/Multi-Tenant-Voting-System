// Display-only tidy-up so "ayebale elizabeth" / "AYEBALE ELIZABETH" show as
// "Ayebale Elizabeth". Names already in mixed case (McDonald, De Souza) are left
// exactly as stored. Nothing is changed in the database.
const capWords = (t) => t.toLowerCase().replace(/(^|[\s\-'’.])([a-z\u00c0-\u024f])/g, (m, pre, ch) => pre + ch.toUpperCase());

export function properName(str) {
  if (!str) return '';
  const t = String(str).trim().replace(/\s+/g, ' ');
  return (t !== t.toLowerCase() && t !== t.toUpperCase()) ? t : capWords(t);
}

// Position titles: only fix an all-lowercase title, so acronyms like "PRO" survive.
export function properTitle(str) {
  if (!str) return '';
  const t = String(str).trim();
  return t === t.toLowerCase() ? capWords(t) : t;
}
