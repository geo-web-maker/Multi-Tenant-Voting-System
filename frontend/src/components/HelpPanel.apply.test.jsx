import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('./VoterRegisterSearch', () => ({ default: () => null }));
vi.mock('./ElectionTimeline', () => ({ default: () => null }));
vi.mock('./FeeSchedule', () => ({ default: () => null }));

import { HelpMenuProvider } from '../context/HelpMenuContext';
import HelpPanel from './HelpPanel';
import { FabTrigger } from './HelpTriggers';

const setup = (page, fabProps = {}) => render(
  <HelpMenuProvider>
    <HelpPanel page={page} supportPhone="256700000000" orgName="Test Org" onShowGuide={() => {}} />
    <FabTrigger {...fabProps} />
  </HelpMenuProvider>,
);
const openMenu = () => fireEvent.click(screen.getByRole('button', { name: 'Help' }));

describe('A2: HelpPanel per page', () => {
  it('voter page lists Sample Ballot, not Nomination Fees, and keeps the code note', () => {
    setup('voter'); openMenu();
    expect(screen.getByText('Sample Ballot Paper')).toBeTruthy();
    expect(screen.queryByText('Nomination Fees')).toBeNull();
    expect(screen.getByText(/Code not arriving/)).toBeTruthy();
    expect(screen.getByText('Contact Support')).toBeTruthy();
  });
  it('apply page lists Nomination Fees, not Sample Ballot, and drops the code note', () => {
    setup('apply'); openMenu();
    expect(screen.getByText('Nomination Fees')).toBeTruthy();
    expect(screen.queryByText('Sample Ballot Paper')).toBeNull();
    expect(screen.queryByText(/Code not arriving/)).toBeNull();
    expect(screen.getByText('Contact Support')).toBeTruthy();
  });
  it('defaults to the voter content when no page is given', () => {
    render(<HelpMenuProvider><HelpPanel supportPhone="" onShowGuide={() => {}} /><FabTrigger /></HelpMenuProvider>);
    openMenu();
    expect(screen.getByText('Sample Ballot Paper')).toBeTruthy();
  });
});

describe('A2: FabTrigger icon-only', () => {
  afterEach(() => { delete window.matchMedia; });

  it('shows the Help word by default', () => {
    setup('voter');
    expect(screen.getByRole('button', { name: 'Help' }).textContent).toContain('Help');
  });
  it('compact shows only the ? and keeps the accessible name', () => {
    setup('apply', { compact: true });
    const b = screen.getByRole('button', { name: 'Help' });
    expect(b.textContent).toBe('?');
    expect(parseInt(b.style.width, 10)).toBeGreaterThanOrEqual(44);
  });
  it('goes icon-only under 400 px even when not compact', () => {
    window.matchMedia = (q) => ({ matches: q === '(max-width: 399px)', media: q, addEventListener() {}, removeEventListener() {} });
    setup('voter');
    expect(screen.getByRole('button', { name: 'Help' }).textContent).toBe('?');
  });
  it('stays full-size at 400 px and wider', () => {
    window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
    setup('voter');
    expect(screen.getByRole('button', { name: 'Help' }).textContent).toContain('Help');
  });
});
