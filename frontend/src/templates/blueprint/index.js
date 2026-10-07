// Blueprint Console entry. Loaded ONLY via the guarded dynamic import in main.jsx (or the test helper).
// Nothing outside src/templates/blueprint/ may import this file statically.
import './blueprint.css';

// viewport-fit=cover is needed for env(safe-area-inset-*) on notched phones. Done here, not in index.html,
// so the default template is unchanged.
if (typeof document !== 'undefined') {
  const vp = document.querySelector('meta[name="viewport"]');
  if (vp && !/viewport-fit=/.test(vp.content)) vp.content = `${vp.content}, viewport-fit=cover`;
}

export { default as TitleBlockHeader } from './TitleBlockHeader.jsx';
export { Stamp, StatusCell, SheetCell, PublicWrap, FieldLabel, StepBar, Avatar, Pill, StatusPill, Stat, Meter, Tick } from './primitives.jsx';
export { default as BottomDock } from './BottomDock.jsx';
export { PositionHeading, CandidateRow } from './BallotParts.jsx';
export { default as BootSplash } from './BootSplash.jsx';
export { initials, STATUS_LABELS, ROLE_LABELS, textOf, cls, statusTone } from './labels.js';
export { default as PhaseBannerView } from './PhaseBannerView.jsx';
export { default as OtpScreen } from './OtpScreen.jsx';
export { default as OtpCells } from './OtpCells.jsx';
export { default as VoterFields } from './VoterFields.jsx';
export { default as ConsoleSidebar } from './ConsoleSidebar.jsx';
export { default as AdminToolbar } from './AdminToolbar.jsx';
export { default as VoterStatsView } from './VoterStatsView.jsx';
export { default as ConsoleFrame } from './ConsoleFrame.jsx';
export { default as SummaryCards } from './SummaryCards.jsx';
export const name = 'blueprint';
