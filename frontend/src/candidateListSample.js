// Made-up names for the Superadmin's "Print sample list". Nothing here is read from or written to the server.
const SHORT = [
  ['President', ['Jane Namukasa', 'Brian Okello', 'Sarah Nankya']],
  ['Vice President', ['Daniel Mugisha', 'Grace Achieng']],
  ['General Secretary', ['Patrick Tumwesigye', 'Ruth Akello']],
  ['Finance Secretary', ['Emmanuel Byaruhanga', 'Elizabeth Ayebale']],
  ['Publicity Secretary', ['Timothy Kato']],
];
// Long names and titles, to see how wrapping and page breaks look before the real list is issued.
const LONG_NAMES = ['Namukasa Nakiyingi Jane-Francesca Atuhaire Mukasa', 'Byaruhanga Emmanuel Kiiza Tumwesigye Junior', 'Ayebale Elizabeth Nankya Kyomuhendo', 'Okello Daniel Achieng Grace Mugisha'];
const LONG = [
  ['Deputy General Secretary, Welfare and Student Affairs', LONG_NAMES],
  ['Representative of Persons with Disabilities and Special Needs', LONG_NAMES],
  ['Vice President', LONG_NAMES],
  ['Sports, Entertainment and Cultural Affairs Secretary', LONG_NAMES],
  ['Publicity Secretary', LONG_NAMES],
  ['Finance Secretary', LONG_NAMES],
];

export function sampleSections(longNames = false) {
  return (longNames ? LONG : SHORT).map(([position, names]) => ({ position, names: [...names] }));
}

export const SAMPLE_LIST_ID = 'LIST-SAMPLE000000';
