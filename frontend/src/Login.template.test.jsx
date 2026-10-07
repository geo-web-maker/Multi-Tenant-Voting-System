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
import { useBlueprint, useDefault, restoreTemplate } from './test/template';

window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });
afterEach(async () => { document.documentElement.removeAttribute('data-theme'); await restoreTemplate(); });
const submit = () => waitFor(() => screen.getByRole('button', { name: /verify & send code/i }), { timeout: 3000 });

describe('BP-T3 login', () => {
  it('default render: no bp- class, no labels added', async () => {
    useDefault();
    const { container } = render(<App />);
    await submit();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('label')).toBeNull();
  });

  it('blueprint: fields found by label, placeholders kept, login-submit label and track kept', async () => {
    await useBlueprint();
    render(<App />);
    const btn = await submit();
    expect(btn).toHaveAttribute('data-track', 'login-submit');
    expect(screen.getByLabelText('Student Registration Number')).toHaveAttribute('name', 'voter-reg-no');
    expect(screen.getByLabelText('Full Name')).toHaveAttribute('name', 'voter-full-name');
    expect(screen.getByPlaceholderText(/^Student Registration Number e\.g\./)).toBeInTheDocument();
  });

  it('blueprint: admin-path toggle still switches fields (with labels)', async () => {
    await useBlueprint();
    render(<App />);
    await submit();
    fireEvent.click(screen.getByRole('button', { name: /are you an admin/i }));
    expect(await screen.findByLabelText('Email address')).toHaveAttribute('name', 'admin-email');
    expect(screen.getByLabelText('Password')).toHaveAttribute('name', 'admin-password');
    expect(screen.getByRole('button', { name: /show password/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /switch to voter login/i }));
    expect(await screen.findByLabelText('Full Name')).toBeInTheDocument();
  });
});
