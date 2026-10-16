import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('./components/VoterRegisterSearch', () => ({ default: () => null }));
vi.mock('./components/ElectionTimeline', () => ({ default: () => null }));
vi.mock('./components/FeeSchedule', () => ({ default: () => null }));

import { navModel, resultsTabLabel } from './phase';
import TitleBlockHeader from './templates/blueprint/TitleBlockHeader';
import { HelpMenuProvider } from './context/HelpMenuContext';
import HelpPanel from './components/HelpPanel';
import { FabTrigger } from './components/HelpTriggers';

const S = (over = {}) => ({
  timezone: 'Africa/Kampala', is_open: true, voting_phase: 'not_started', applications_phase: 'open',
  vetting_phase: 'not_started', voting_scheduled: true, public_results_mode: 'live', ...over,
});
const CLOSED = { applications_phase: 'ended', vetting_phase: 'ended' };

describe('phase-aware public nav', () => {
  it.each([
    ['applications open', S(), 'Apply', null],
    ['applications closed, vetting going', S({ applications_phase: 'ended', vetting_phase: 'open' }), null, null],
    ['vetting done, voting not started', S(CLOSED), 'Candidate List', null],
    ['voting open', S({ ...CLOSED, voting_phase: 'open' }), null, 'Live Results'],
    ['voting ended', S({ ...CLOSED, voting_phase: 'ended' }), null, 'Provisional Results'],
    ['certified', S({ ...CLOSED, voting_phase: 'ended', is_certified: true }), null, 'Official Results'],
  ])('%s', (_n, status, slot, results) => {
    const m = navModel(status);
    expect(m.showApply ? 'Apply' : m.candidateList ? 'Candidate List' : null).toBe(slot);
    expect(m.showResults ? m.resultsLabel : null).toBe(results);
  });

  it('never calls a vote-hiding election "Live"', () => {
    const open = S({ ...CLOSED, voting_phase: 'open' });
    expect(resultsTabLabel({ ...open, public_results_mode: 'closed' })).toBe('Turnout & Roll');
    expect(resultsTabLabel({ ...open, public_results_mode: 'certified' })).toBe('Turnout & Roll');
    expect(resultsTabLabel({ ...open, voting_phase: 'ended', public_results_mode: 'closed' })).toBe('Provisional Results');
  });

  it('unknown status keeps today\'s nav', () => {
    expect(navModel(null)).toMatchObject({ resultsLabel: 'Live Results', showApply: true, showResults: true, candidateList: false });
  });

  const header = (status, over = {}) => render(<TitleBlockHeader orgName="Org" view="voter" step={1} theme="light"
    status={status} onToggleTheme={() => {}} onVoteNow={() => {}} onShowCandidates={over.onShowCandidates || (() => {})} onNavigate={() => {}} />);

  it('header: Vote Now is always there; Candidate List takes the Apply slot with its own data-track', () => {
    const onShowCandidates = vi.fn();
    header(S(CLOSED), { onShowCandidates });
    expect(screen.getByRole('button', { name: 'Vote Now' })).toHaveAttribute('data-track', 'nav-vote');
    expect(screen.queryByRole('button', { name: 'Apply' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Results|Turnout/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Candidate List' }));
    expect(onShowCandidates).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Candidate List' })).toHaveAttribute('data-track', 'nav-candidates');
  });

  it('header: during voting the tab is named by the results mode', () => {
    header(S({ ...CLOSED, voting_phase: 'open', public_results_mode: 'closed' }));
    expect(screen.getByRole('button', { name: 'Turnout & Roll' })).toHaveAttribute('data-track', 'nav-results');
  });

  it('Help drops the ballot preview only while the header carries the Candidate List', () => {
    const open = (hide) => { const r = render(<HelpMenuProvider><HelpPanel page="voter" supportPhone="1" onShowGuide={() => {}} hideSampleBallot={hide} /><FabTrigger /></HelpMenuProvider>);
      fireEvent.click(screen.getByRole('button', { name: 'Help' })); return r; };
    open(true);
    expect(screen.queryByText('Sample Ballot Paper')).toBeNull();
  });
  it('Help shows the ballot preview otherwise', () => {
    render(<HelpMenuProvider><HelpPanel page="voter" supportPhone="1" onShowGuide={() => {}} /><FabTrigger /></HelpMenuProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    expect(screen.getByText('Sample Ballot Paper')).toBeTruthy();
  });
});
