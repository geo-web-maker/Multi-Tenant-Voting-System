/** Helpers for the voter-import "Match columns" step. `mapping` is { field: ['3', '4'] } (select values, '' = none). */

export const toMappingState = suggested =>
  Object.fromEntries(Object.entries(suggested || {}).map(([k, idxs]) => [k, idxs.map(String)]));

export const mappingPayload = mapping =>
  Object.fromEntries(Object.entries(mapping)
    .map(([k, vals]) => [k, vals.filter(v => v !== '').map(Number)])
    .filter(([, idxs]) => idxs.length));

export const missingRequired = (data, mapping) =>
  (data?.targets || []).filter(t => t.required && !(mapping[t.key] || []).some(v => v !== ''));
