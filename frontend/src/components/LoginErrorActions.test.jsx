import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LoginErrorActions from './LoginErrorActions';
import { HelpMenuProvider, useHelpMenu } from '../context/HelpMenuContext';
import { loginGuidance } from '../loginErrors';

const RegisterProbe = () => { const { showRegister } = useHelpMenu(); return <div data-testid="reg">{showRegister ? 'open' : 'closed'}</div>; };
const show = (guide, extra = {}) => render(
  <HelpMenuProvider>
    <LoginErrorActions action={guide.action} support={guide.support} supportContact="256700000000" orgName="Union" studentId="23/U/ABC/00001/GV" {...extra} />
    <RegisterProbe />
  </HelpMenuProvider>);

describe('A5 login error action buttons (one case per playbook row)', () => {
  it('Student ID not found: register button + support link', () => {
    show(loginGuidance('Student ID not found.', 'not_on_roll'));
    expect(screen.getByRole('button', { name: /check the voter register/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /contact support/i }).getAttribute('href')).toMatch(/^https:\/\/wa\.me\/256700000000\?text=/);
  });
  it('Name mismatch: register button only', () => {
    show(loginGuidance('Name mismatch. Please provide your full registered names.', 'name_mismatch'));
    expect(screen.getByRole('button', { name: /check the voter register/i })).toBeTruthy();
    expect(screen.queryByRole('link', { name: /contact support/i })).toBeNull();
  });
  it('Already voted: support link only', () => {
    show(loginGuidance('Already voted.', 'already_voted'));
    expect(screen.getByRole('link', { name: /contact support/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /register/i })).toBeNull();
  });
  it('No phone found: contact-change link', () => {
    show(loginGuidance('No phone found.', 'no_phone'));
    const a = screen.getByRole('link', { name: /request a contact change/i });
    expect(decodeURIComponent(a.getAttribute('href'))).toMatch(/no phone number on file/i);
  });
  it('unknown text and object detail: no buttons, no crash', () => {
    for (const d of ['Something new.', { a: 1 }, undefined]) {
      const { container, unmount } = show(loginGuidance(d, undefined));
      expect(container.querySelector('a,button')).toBeNull();
      unmount();
    }
  });
  it('the register button opens the register and closes the error', () => {
    const onNavigate = vi.fn();
    show(loginGuidance('Student ID not found.', 'not_on_roll'), { onNavigate });
    fireEvent.click(screen.getByRole('button', { name: /check the voter register/i }));
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(screen.getByTestId('reg').textContent).toBe('open');
  });
  it('no support contact configured: support and contact-change links are not shown, register still is', () => {
    show(loginGuidance('Student ID not found.', 'not_on_roll'), { supportContact: '' });
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByRole('button', { name: /check the voter register/i })).toBeTruthy();
  });
  it('the prefilled support message never asks for the code', () => {
    show(loginGuidance('Already voted.', 'already_voted'));
    const href = decodeURIComponent(screen.getByRole('link', { name: /contact support/i }).getAttribute('href'));
    expect(href).toMatch(/never send your code/i);
  });
});
