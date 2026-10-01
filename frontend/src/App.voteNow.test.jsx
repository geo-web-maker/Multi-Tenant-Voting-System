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
import { ADMIN_TOKEN_KEY } from './api';

window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));

// Unsigned but well-formed JWT (role + far-future exp) so restoreAdminView() keeps it at boot.
const b64 = (o) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const ADMIN_JWT = `${b64({ alg: 'none' })}.${b64({ role: 'superadmin', exp: 4102444800 })}.sig`;

const clickVoteNow = async () => {
  const btn = await waitFor(() => screen.getByRole('button', { name: /vote now/i }), { timeout: 3000 });
  fireEvent.click(btn);
};

describe('WP-7c: confirm before Vote Now signs an admin out', () => {
  beforeEach(() => { sessionStorage.clear(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('admin token + confirm=false keeps the token', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<App />);
    await clickVoteNow();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(ADMIN_TOKEN_KEY)).toBe(ADMIN_JWT);
  });

  it('admin token + confirm=true clears the token', async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, ADMIN_JWT);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<App />);
    await clickVoteNow();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull();
  });

  it('no token -> no dialog', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<App />);
    await clickVoteNow();
    expect(confirm).not.toHaveBeenCalled();
  });
});
