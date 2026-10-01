import { describe, it, expect, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
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

  it('login placeholders animate in the child component, and stop once the user types', async () => {
    sessionStorage.clear();
    vi.useFakeTimers();
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    const reg = () => screen.getByPlaceholderText(/^Student Registration Number e\.g\./);
    const first = reg().getAttribute('placeholder');
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    const second = reg().getAttribute('placeholder');
    expect(second).not.toEqual(first);
    fireEvent.change(reg(), { target: { value: '23/U' } });
    const frozen = reg().getAttribute('placeholder');
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(reg().getAttribute('placeholder')).toEqual(frozen);
    vi.useRealTimers();
  });
});
