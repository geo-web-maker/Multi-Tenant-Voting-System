import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

// Control exactly when /health answers; everything else the app fetches on boot just never resolves.
let healthResolve;
vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal()),             // keep the real constants (token keys, API_BASE, getErrorMessage)
  default: {
    get: vi.fn((url) => ((url === '/health' || url === '/')
      ? new Promise((res) => { healthResolve = () => res({ data: {} }); })
      : new Promise(() => {}))),
    post: vi.fn(() => new Promise(() => {})),
    interceptors: { request: { use() {} }, response: { use() {} } },
  },
}));
vi.mock('./analytics', () => ({ initAnalytics: () => {}, trackPage: () => {}, pageName: () => 'x' }));

import App from './App';

// jsdom has no matchMedia; App reads it for the initial theme.
window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));

const SPLASH_COPY = /Loading election details|waking up/i;
const ANY_SPLASH = /Loading election details|waking up|Server is up|Secure connection established/i;   // every stage

describe('boot splash (WP-3)', () => {
  beforeEach(() => { vi.useFakeTimers(); sessionStorage.clear(); });
  afterEach(() => { vi.useRealTimers(); });

  it('never shows the splash when /health answers inside the grace period', async () => {
    render(<App />);
    expect(screen.queryByText(SPLASH_COPY)).toBeNull();          // nothing flashed at t=0
    await act(async () => { await vi.advanceTimersByTimeAsync(100); healthResolve(); await vi.advanceTimersByTimeAsync(0); });
    expect(screen.queryByText(ANY_SPLASH)).toBeNull();           // released straight to the app: no stage ever shown
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.queryByText(ANY_SPLASH)).toBeNull();           // ...and no late splash either
  });

  it('shows the splash when the server is slow (cold start)', async () => {
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByText(SPLASH_COPY)).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText(/waking up/i)).toBeInTheDocument(); // the honest cold-start copy still appears
  });
});
