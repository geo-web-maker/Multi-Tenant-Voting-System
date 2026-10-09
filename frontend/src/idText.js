// Per-organisation wording for the voter ID ("Student Registration Number" at one org, "Student Number" at
// another), the example IDs/names shown in the login placeholders, and the format hint in login errors.
// It comes from the org's branding (superadmin -> Branding) and is held in this tiny store so any component can
// read it without prop-drilling. Anything left blank falls back to the original wording, so an org that has set
// nothing sees exactly what it saw before.
import { useSyncExternalStore } from 'react';

export const DEFAULT_ID_LABEL = 'Student Registration Number';
export const DEFAULT_ID_EXAMPLES = [
  '23/U/BCS/10245/GV', '22/U/ISD/08940/PD', '23/U/AGE/11223/GV', '21/U/BSE/44556/PE', '23/U/BPH/00341/GV',
];
export const DEFAULT_NAME_EXAMPLES = [
  'Ayebale Elizabeth', 'Namusoke Dorothy Nalwadda', 'Kaggwa Paul', 'Sserwadda Valentino', 'Bakanansa Jesca',
];
const DEFAULT_HINT = 'Use the format 23/U/XXX/00000/GV exactly as on your student ID.';

const clean = (v) => String(v ?? '').trim();
const cleanList = (v) => (Array.isArray(v) ? v : []).map(clean).filter(Boolean);

/** Pure: branding object (or null) -> the wording every screen uses. */
export function buildIdText(branding) {
  const b = branding || {};
  const label = clean(b.id_label) || DEFAULT_ID_LABEL;
  const customLabel = label !== DEFAULT_ID_LABEL;
  const ids = cleanList(b.id_examples);
  const names = cleanList(b.name_examples);
  const noun = customLabel ? label.toLowerCase() : 'registration number';   // for sentences: "that ___ was not found"
  let hint = clean(b.id_format_hint);
  if (!hint) {
    // An org that has described its own IDs must never be shown another org's format.
    hint = ids.length || customLabel
      ? (ids.length ? `Enter it exactly as on your student ID, for example ${ids[0]}.` : '')
      : DEFAULT_HINT;
  }
  return {
    label,                                         // "Student Number"
    short: customLabel ? label : 'Registration Number',   // admin tables / column titles
    noun,                                          // "student number"
    nounCap: noun.charAt(0).toUpperCase() + noun.slice(1),
    ids: ids.length ? ids : DEFAULT_ID_EXAMPLES,
    names: names.length ? names : DEFAULT_NAME_EXAMPLES,
    firstId: ids[0] || DEFAULT_ID_EXAMPLES[0],
    hint,
  };
}

let raw = {};                    // the wording fields of the last branding seen
let current = buildIdText(null);
const listeners = new Set();
const pick = (b) => ({ id_label: b?.id_label, id_examples: b?.id_examples, name_examples: b?.name_examples, id_format_hint: b?.id_format_hint });

export const getIdText = () => current;
export function setIdText(branding) {
  raw = pick(branding);
  current = buildIdText(raw);
  listeners.forEach((l) => l());
}
/** Change part of the wording (e.g. the label set during a voter import) and keep the rest. */
export function patchIdText(partial) {
  setIdText({ ...raw, ...partial });
}
export function useIdText() {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    getIdText,
    getIdText,
  );
}
