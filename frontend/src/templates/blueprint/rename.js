// Mockup class -> production class (BLUEPRINT_TEMPLATE_GUIDE.md Appendix C). Used by parity.test.js.
// Not imported by any runtime code, so it never reaches a bundle.
export const RENAME = {
  top:'bp-top', tl:'bp-tl', logo:'bp-logo', bt:'bp-bt', crumb:'bp-crumb', cell:'bp-cell', dot:'bp-dot', rule:'bp-rule',
  wrap:'bp-wrap', wide:'bp-wide', card:'bp-card', in:'bp-in', f:'bp-focus', btn:'bp-btn', g:'bp-ghost', sm:'bp-sm',
  lnk:'bp-lnk', ban:'bp-ban', w:'bp-warn', alt:'bp-alt', pos:'bp-pos', cand:'bp-cand', av:'bp-av', tick:'bp-tick',
  on:'bp-on', dock:'bp-dock', big:'bp-big', stat:'bp-stat', pill:'bp-pill', n:'bp-neg', m:'bp-mute', row:'bp-meter',
  t:'bp-t', bar:'bp-bar', shell:'bp-shell', side:'bp-side', brand:'bp-brand', main:'bp-main', grid:'bp-grid',
  g2:'bp-g2', g4:'bp-g4', k:'bp-k2', rs:'bp-rs', cen:'bp-cen', otp:'bp-otp', steps:'bp-steps', chart:'bp-chart',
  hot:'bp-hot', two:'bp-two', chip:'bp-chip', lg:'bp-lg', sh:'bp-sheet', st:'bp-status', ov:'bp-ov', sc:'bp-sc',
  mu:'bp-mu', num:'bp-num', mono:'bp-mono',
};
// Tooling classes that are NOT ported (the parity test ignores them).
export const TOOLING = ['tb', 'dev', 'gd', 'sp', 'sw'];
