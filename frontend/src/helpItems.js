// A2 (WP-7b): which Help entries each page shows, and when the floating Help button renders. Pure.
// Keys, in display order. 'support' stands for Contact Support plus the configured per-reason contacts.
// Only "Sample Ballot only on voter" and "Nomination Fees only on apply" come from the card; the other
// placements keep the panel's existing behaviour and are the one place to edit if the §4.1a table says otherwise.
const ITEMS = {
  voter: ['code-note', 'sample-ballot', 'register', 'timeline', 'support'],
  apply: ['register', 'timeline', 'fees', 'support'],
};

export const helpItemsFor = (page) => [...(ITEMS[page] || ITEMS.voter)];

// Ballot page (voter step 3) owns its own inline Help in its footer bar, so no floating button there.
export const showHelpFab = (view, step) => (view === 'voter' && step !== 3) || view === 'apply';

// Contact reasons offered on each page. Voter keeps the single generic "Contact Support" entry.
export const supportReasonsFor = (page) => (page === 'apply' ? ['Application problem', 'Payment'] : []);

// data-track ids (WP-7b); all satisfy the tracker's ^[a-z0-9_-]{2,40}$ rule.
export const HELP_TRACK = { fab: 'help-fab', fees: 'help-fees', timeline: 'help-timeline', support: 'help-support' };

// The FAB fades out while one of these has focus (the phone keyboard is then open).
export const isTextEntry = (el) => !!el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)
  && !/^(button|submit|checkbox|radio|reset|image|file)$/i.test(el.type || '');
