import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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

window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));

// Unsigned but well-formed JWT (role + far-future exp) so restoreAdminView() keeps it at boot.
const b64 = (o) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const ADMIN_JWT = `${b64({ alg: 'none' })}.${b64({ role: 'superadmin', exp: 4102444800 })}.sig`;

const clickVoteNow = async () => {
  const btn = await waitFor(() => screen.getByRole('button', { name: /vote now/i }), { timeout: 3000 });
  fireEvent.click(btn);
};

const renderApp = () => render(<UIFeedbackProvider><App /></UIFeedbackProvider>);

describe('WP-7c: in-app confirm before Vote Now signs an admin out (no browser dialog)', () => {
  beforeEach(() => { sessionStorage.clear(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('admin token + "Stay signed in" keeps the token', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    const native = vi.spyOn(window, 'confirm');
    renderApp();
    await clickVoteNow();
    const dlg = await screen.findByRole('dialog', { name: /sign out\?/i });
    expect(dlg).toHaveTextContent('You will be signed out. Continue?');
    fireEvent.click(screen.getByRole('button', { name: /stay signed in/i }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /sign out\?/i })).toBeNull());
    expect(native).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(ADMIN_TOKEN_KEY)).toBe(ADMIN_JWT);
  });

  it('admin token + Escape also keeps the token', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    renderApp();
    await clickVoteNow();
    await screen.findByRole('dialog', { name: /sign out\?/i });
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /sign out\?/i })).toBeNull());
    expect(sessionStorage.getItem(ADMIN_TOKEN_KEY)).toBe(ADMIN_JWT);
  });

  it('admin token + "Sign out" clears the token', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    const native = vi.spyOn(window, 'confirm');
    renderApp();
    await clickVoteNow();
    await screen.findByRole('dialog', { name: /sign out\?/i });
    fireEvent.click(screen.getByRole('button', { name: /^sign out$/i }));
    await waitFor(() => expect(sessionStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull());
    expect(native).not.toHaveBeenCalled();
  });

  it('no token -> no dialog', async () => {
    const native = vi.spyOn(window, 'confirm');
    renderApp();
    await clickVoteNow();
    expect(screen.queryByRole('dialog', { name: /sign out\?/i })).toBeNull();
    expect(native).not.toHaveBeenCalled();
  });
});
