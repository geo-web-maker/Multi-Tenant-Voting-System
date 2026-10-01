import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

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
    expect(screen.queryByText('Contact Support')).toBeNull(); // replaced by the two reasoned links below
    expect(screen.getByText('Application problem')).toBeTruthy();
    expect(screen.getByText('Payment')).toBeTruthy();
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

describe('A2 extras: support reasons on Apply', () => {
  it('each reason is a buildSupportLink WhatsApp link with that reason and never asks for the code', () => {
    setup('apply'); openMenu();
    for (const reason of ['Application problem', 'Payment']) {
      const a = screen.getByText(reason).closest('a');
      expect(a.href.startsWith('https://wa.me/256700000000?text=')).toBe(true);
      const text = decodeURIComponent(a.href.split('text=')[1]);
      expect(text).toContain(`Problem: ${reason} (never send your code).`);
      expect(text).toContain('Test Org');
    }
  });
  it('voter keeps the single generic Contact Support link', () => {
    setup('voter'); openMenu();
    expect(screen.getByText('Contact Support').closest('a').href).toContain('wa.me/256700000000');
    expect(screen.queryByText('Application problem')).toBeNull();
  });
  it('no support entries without a configured number', () => {
    render(<HelpMenuProvider><HelpPanel page="apply" supportPhone="" onShowGuide={() => {}} /><FabTrigger compact /></HelpMenuProvider>);
    openMenu();
    expect(screen.queryByText('Payment')).toBeNull();
  });
});

describe('A2 extras: data-track ids', () => {
  it('FAB, timeline, fees and support carry the agreed ids', () => {
    setup('apply'); 
    expect(screen.getByRole('button', { name: 'Help' }).getAttribute('data-track')).toBe('help-fab');
    openMenu();
    expect(screen.getByText('Election Timeline').getAttribute('data-track')).toBe('help-timeline');
    expect(screen.getByText('Nomination Fees').getAttribute('data-track')).toBe('help-fees');
    expect(screen.getByText('Payment').closest('a').getAttribute('data-track')).toBe('help-support');
    expect(screen.getByText('Application problem').closest('a').getAttribute('data-track')).toBe('help-support');
  });
  it('voter Contact Support is tracked as help-support', () => {
    setup('voter'); openMenu();
    expect(screen.getByText('Contact Support').closest('a').getAttribute('data-track')).toBe('help-support');
  });
});

describe('A2 extras: fade while typing', () => {
  const withInput = (type = 'text') => render(
    <HelpMenuProvider>
      <input aria-label="field" type={type} />
      <HelpPanel page="apply" supportPhone="1" onShowGuide={() => {}} />
      <FabTrigger compact />
    </HelpMenuProvider>,
  );
  const fab = () => document.querySelector('[data-track="help-fab"]');

  it('fades and ignores taps while a text field has focus, returns on blur', () => {
    withInput();
    expect(fab().style.opacity).toBe('');
    act(() => { screen.getByLabelText('field').focus(); });
    expect(fab().style.opacity).toBe('0');
    expect(fab().style.pointerEvents).toBe('none');
    act(() => { screen.getByLabelText('field').blur(); });
    expect(fab().style.opacity).toBe('');
  });
  it('a checkbox or button taking focus does not fade it', () => {
    withInput('checkbox');
    act(() => { screen.getByLabelText('field').focus(); });
    expect(fab().style.opacity).toBe('');
  });
  it('stays visible while the menu is open so it can be closed', () => {
    withInput();
    fireEvent.click(screen.getByRole('button', { name: 'Help' }));
    act(() => { screen.getByLabelText('field').focus(); });
    expect(fab().style.opacity).toBe('');
  });
});
