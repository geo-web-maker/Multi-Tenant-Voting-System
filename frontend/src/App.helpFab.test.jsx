import { describe, it, expect, vi, beforeEach } from 'vitest';
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

window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));

describe('A2: floating Help in the App shell', () => {
  beforeEach(() => { sessionStorage.clear(); });

  it('renders on the voter login and, icon-only, on Apply', async () => {
    render(<App />);
    const onVoter = await waitFor(() => screen.getByRole('button', { name: 'Help' }), { timeout: 3000 });
    expect(onVoter.textContent).toContain('Help');
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Help' }).textContent).toBe('?'));
  });
});
