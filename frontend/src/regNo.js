// Registration numbers are stored in ONE canonical form (lowercase, no spaces) so that every
// lookup is a plain exact match. Only their *display* is capitalised: use regNo() wherever a
// registration number is shown to a person. Never send the result back as a key or filter.
export const regNo = (sid) => (sid == null ? '' : String(sid).toUpperCase());
