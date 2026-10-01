import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import appSource from './App.jsx?raw';

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

window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));

describe('WP-6b: no typing-placeholder animation state in App', () => {
  it('App.jsx owns no animation state', () => {
    expect(appSource).not.toMatch(/setPlaceholderText|setTypingSpeed|setIsDeleting|setLoopNum/);
  });

  it('login placeholders stay static while idle', async () => {
    sessionStorage.clear();
    vi.useFakeTimers();
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    const get = () => [
      screen.getByPlaceholderText(/^Student Registration Number e\.g\. .+/).getAttribute('placeholder'),
      screen.getByPlaceholderText(/^Full Name e\.g\. .+/).getAttribute('placeholder'),
    ];
    const first = get();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(get()).toEqual(first);
    vi.useRealTimers();
  });
});
