// Builds the printable versions of an application from its ORIGINAL submission snapshot plus the
// corrections made since: [{ at, snapshot }] (oldest first), where each snapshot is the printed content
// right after that correction. Returns newest-first: [ current (edited), ...earlier edits, original ].
// A never-edited application yields just the original. Corrections that changed nothing printed
// (e.g. payment details only) don't get a page of their own.
export const PRINTED_FIELDS = [
  ['student_id', 'registration number'],
  ['full_name', 'name'],
  ['position_title', 'position'],
  ['manifesto', 'manifesto'],
  ['image_url', 'photo'],
];

const norm = (v) => (v == null ? '' : String(v));
const differs = (a, b) => PRINTED_FIELDS.filter(([k]) => k === 'student_id'
  ? norm(a[k]).toLowerCase() !== norm(b[k]).toLowerCase()
  : norm(a[k]) !== norm(b[k])).map(([, label]) => label);

export function applicationVersions(snapshot, edits) {
  if (!snapshot) return [];
  const chain = [{ ...snapshot, kind: 'original' }];
  for (const e of Array.isArray(edits) ? edits : []) {
    const prev = chain[chain.length - 1];
    const next = { ...snapshot, ...(e.snapshot || {}), edited_at: e.at };
    const changed = differs(prev, next);
    if (changed.length) chain.push({ ...next, changedFields: changed, kind: 'edit' });
  }
  const last = chain.length - 1;
  return chain.map((v, i) => (i === 0 ? v : { ...v, kind: i === last ? 'current' : 'earlier' })).reverse();
}
