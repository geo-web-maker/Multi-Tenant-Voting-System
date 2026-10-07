import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal()),
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: { request: { use() {} }, response: { use() {} } },
  },
}));
vi.mock('./analytics', () => ({ initAnalytics: () => {}, trackPage: () => {}, pageName: () => 'x' }));

import App from './App';
import { UIFeedbackProvider } from './components/UIFeedback';
import { ADMIN_TOKEN_KEY } from './api';
import { useBlueprint, useDefault, restoreTemplate } from './test/template';

window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));

const b64 = (o) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const ADMIN_JWT = `${b64({ alg: 'none' })}.${b64({ role: 'superadmin', exp: 4102444800 })}.sig`;
const nav = () => waitFor(() => screen.getByRole('button', { name: /vote now/i }), { timeout: 3000 });

beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });
afterEach(async () => { vi.restoreAllMocks(); document.documentElement.removeAttribute('data-theme'); await restoreTemplate(); });

describe('BP-T2 default render is untouched', () => {
  it('has no bp- class and no data-template', async () => {
    useDefault();
    const { container } = render(<App />);
    await nav();
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('nav.no-print')).not.toBeNull();   // today's nav block
  });
});

describe('BP-T2 blueprint public shell', () => {
  beforeEach(async () => { await useBlueprint(); });

  it('renders the title-block header instead of the old nav, with the same labels/data-track', async () => {
    const { container } = render(<App />);
    await nav();
    expect(document.documentElement.dataset.template).toBe('blueprint');
    expect(container.querySelector('header.bp-top')).not.toBeNull();
    expect(container.querySelector('nav.no-print')).toBeNull();
    expect(screen.getByRole('button', { name: 'Vote Now' })).toHaveAttribute('data-track', 'nav-vote');
    expect(screen.getByRole('button', { name: 'Live Results' })).toHaveAttribute('data-track', 'nav-results');
    expect(screen.getByRole('button', { name: 'Apply' })).toHaveAttribute('data-track', 'nav-apply');
  });

  it('wraps the voter content in .bp-wrap (and only then)', async () => {
    const { container } = render(<App />);
    await nav();
    expect(container.querySelector('.bp-wrap')).not.toBeNull();
  });

  it('Vote Now still goes through handleVoteNow (admin-session confirm preserved, in-app dialog)', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    const native = vi.spyOn(window, 'confirm');
    render(<UIFeedbackProvider><App /></UIFeedbackProvider>);
    fireEvent.click(await nav());
    fireEvent.click(await screen.findByRole('button', { name: /stay signed in/i }));
    expect(native).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(ADMIN_TOKEN_KEY)).toBe(ADMIN_JWT);
  });

  it('theme toggle flips data-theme and the localStorage "theme" key', async () => {
    render(<App />);
    await nav();
    const before = document.documentElement.getAttribute('data-theme');
    const label = before === 'dark' ? 'Light' : 'Dark';
    fireEvent.click(screen.getByRole('button', { name: label }));
    const after = before === 'dark' ? 'light' : 'dark';
    await waitFor(() => expect(document.documentElement.getAttribute('data-theme')).toBe(after));
    expect(localStorage.getItem('theme')).toBe(after);
  });

  it('Live Results / Apply switch view; Back to Admin shows only on results/apply with an admin role', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    render(<App />);
    // restored admin session lands on a dashboard; the public header is shown on every App-shell page
    await waitFor(() => screen.getByRole('button', { name: 'Live Results' }), { timeout: 3000 });
    expect(screen.queryByRole('button', { name: 'Back to Admin' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Live Results' }));
    await waitFor(() => screen.getByRole('button', { name: 'Back to Admin' }));
    expect(screen.getByRole('button', { name: 'Live Results' })).toHaveAttribute('aria-current', 'page');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Back to Admin' })); });
    expect(screen.queryByRole('button', { name: 'Back to Admin' })).toBeNull();
  });
});
