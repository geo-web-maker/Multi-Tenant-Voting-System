// Title-block header (BP-T2 public variant, BP-T7a console variant). Receives the same state and handlers the old <nav> used.
// Console variant (a `role` is passed for dashboard views): role as the brand subtitle, a `group / tab` crumb and the
// "active tab / tab count" sheet cell, all read from the chrome store the sidebar publishes to.
import { useEffect } from 'react';
import { Stamp, StatusCell, SheetCell } from './primitives';
import LiveStatus from './LiveStatus';
import { setChrome, useChrome } from '../../templateChrome';
import { derivePhase } from '../../phase';

const NAV = [
  { key: 'vote', label: 'Vote Now', track: 'nav-vote' },
  { key: 'results', label: 'Live Results', track: 'nav-results' },
  { key: 'apply', label: 'Apply', track: 'nav-apply' },
];

export default function TitleBlockHeader({
  orgName, logoUrl, logoNeedsInvert = false, phase = null, status = null, view, step, theme,
  onToggleTheme, onVoteNow, onNavigate, showBackToAdmin = false, onBackToAdmin, role = '',
}) {
  const chrome = useChrome();
  // Applications open -> the Apply tab gets a soft highlight (replaces the old "Apply now" button in the banner).
  const applyOpen = (status ? derivePhase(status)?.state : phase) === 'apply_open';
  // Flat dashboards have no groups: the sidebar uses the role as the crumb group, so publish it from here.
  useEffect(() => {
    setChrome({ role });
    return () => setChrome({ role: '' });
  }, [role]);

  // Same active rule as the default nav: Vote Now is active only on the first voter step.
  const active = view === 'voter' && step === 1 ? 'vote' : (view === 'results' || view === 'apply') ? view : null;
  const onClick = { vote: onVoteNow, results: () => onNavigate('results'), apply: () => onNavigate('apply') };
  // D5: voter flow shows "step n / 3" (1.5 = choosing a phone, still sheet 1; the post-ballot step has no sheet).
  const sheet = view === 'voter' && step >= 1 && step < 4 ? Math.floor(step) : null;
  // D5, consoles: "active tab / tab count" once the sidebar has published it.
  const consoleSheet = role && chrome.tabCount > 0 ? { n: chrome.tabIndex, of: chrome.tabCount } : null;

  return (
    <header className="bp-top no-print">
      <div className="bp-tl">
        <Stamp name={orgName} logoUrl={logoUrl} invert={logoNeedsInvert} />
        <div className="bp-bt">
          <b title={orgName}>{orgName}</b>
          <small>{role || 'Election Portal'}</small>
        </div>
      </div>
      {role && chrome.group && chrome.tab && (
        <div className="bp-crumb">
          {chrome.group} <i aria-hidden="true">/</i> <b>{chrome.tab}</b>
        </div>
      )}
      <nav aria-label="Main">
        {NAV.map((n) => (
          <button
            key={n.key} type="button" data-track={n.track} onClick={onClick[n.key]}
            aria-current={active === n.key ? 'page' : undefined}
            className={active === n.key ? 'bp-on' : (n.key === 'apply' && applyOpen ? 'bp-hl' : undefined)}
          >
            {n.label}
          </button>
        ))}
        {showBackToAdmin && (
          <button type="button" className="bp-ghost" onClick={onBackToAdmin}>Back to Admin</button>
        )}
      </nav>
      <div className="bp-cell bp-theme">
        <button
          type="button" onClick={onToggleTheme}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
      {/* `status` (raw /election-status) gives a live cell with countdown; `phase` alone still gives the static label. */}
      {status ? <LiveStatus status={status} /> : <StatusCell phase={phase} />}
      {sheet && <SheetCell n={sheet} of={3} />}
      {consoleSheet && <SheetCell n={consoleSheet.n} of={consoleSheet.of} />}
      <i className="bp-rule" aria-hidden="true" />
    </header>
  );
}
