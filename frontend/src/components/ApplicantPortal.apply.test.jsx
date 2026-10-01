import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
}));
const mockTrack = vi.fn();
vi.mock('../analytics', () => ({ trackStep: (...a) => mockTrack(...a) }));
vi.mock('../paymentInfo', () => ({ usePaymentInfo: () => null }));
vi.mock('../hooks/usePolling', () => ({ default: () => {} }));
vi.mock('../context/HelpMenuContext', () => ({ useHelpMenu: () => ({ openFees: () => {} }) }));
vi.mock('./MobileMoneyNumber', () => ({ default: () => null }));

import ApplicantPortal from './ApplicantPortal';
import { saveDraft } from '../session';
import { resetBootstrapCache } from '../bootstrap';

const file = (name, size = 1000, type = 'image/jpeg') => {
  const f = new File(['x'], name, { type, lastModified: 1 });
  Object.defineProperty(f, 'size', { value: size });
  return f;
};
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

let calls;
beforeEach(() => {
  cleanup(); mockGet.mockReset(); mockPost.mockReset(); mockTrack.mockReset(); resetBootstrapCache();
  sessionStorage.clear(); localStorage.clear();
  calls = [];
  Element.prototype.scrollIntoView = vi.fn();
  // Startup now comes from one /public/bootstrap request (E1); same data as the old two endpoints.
  const POSITIONS = [{ _id: 'p1', title: 'Chairperson', application_fee: 0 }];
  const STATUS = { approval_policy: 'majority_total' };
  mockGet.mockImplementation((url) => Promise.resolve({
    data: url === '/public/bootstrap' ? { branding: {}, status: STATUS, positions: POSITIONS }
      : url === '/positions' ? POSITIONS : STATUS,
  }));
});
afterEach(() => { vi.useRealTimers(); });

const fileInputs = (c) => c.querySelectorAll('input[type=file]');
const form = (c) => c.querySelector('form');

async function fillAll(c, { photo = false } = {}) {
  await screen.findByText('Chairperson');
  fireEvent.change(screen.getByPlaceholderText(/22\/U\/IED/), { target: { value: '  22/u/ied/1086/gv ' } });
  fireEvent.change(screen.getByPlaceholderText(/Ayebale/), { target: { value: 'Ayebale Elizabeth' } });
  fireEvent.click(screen.getByText('Chairperson'));
  fireEvent.change(screen.getByPlaceholderText(/I am running/), { target: { value: 'Vote for me' } });
  fireEvent.click(screen.getByText('Bank Transfer'));
  fireEvent.change(fileInputs(c)[0], { target: { files: [file('receipt.jpg')] } });
  if (photo) fireEvent.change(fileInputs(c)[1], { target: { files: [file('face.jpg')] } });
}
URL.createObjectURL = URL.createObjectURL || (() => 'blob:x');

describe('B1: apply form validation', () => {
  it('A2: receipt picker accepts the four image types and no pdf', async () => {
    const { container } = render(<ApplicantPortal />);
    await screen.findByText('Chairperson');
    const accept = fileInputs(container)[0].getAttribute('accept');
    expect(accept.split(',').sort()).toEqual(['image/gif', 'image/jpeg', 'image/png', 'image/webp']);
    expect(accept).not.toMatch(/pdf/);
  });

  it('A3: a 6 MB file shows an error and makes no API call', async () => {
    const { container } = render(<ApplicantPortal />);
    await screen.findByText('Chairperson');
    fireEvent.change(fileInputs(container)[0], { target: { files: [file('big.jpg', 6 * 1048576)] } });
    expect(await screen.findByText(/limit is 5 MB/)).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockTrack).toHaveBeenCalledWith('apply', 'submit_blocked', 'too_large');
  });

  it('A5: an empty submit lists every missing field, marks each, and focuses the first', async () => {
    const { container } = render(<ApplicantPortal />);
    await screen.findByText('Chairperson');
    fireEvent.submit(form(container));
    const alert = await screen.findByRole('alert');
    for (const label of ['Student registration number', 'Full name', 'Position', 'Manifesto', 'Payment method', 'Payment receipt']) {
      expect(alert.textContent).toContain(label);
    }
    for (const f of ['student_id', 'full_name', 'position_id', 'manifesto', 'payment_method', 'payment_proof']) {
      expect(container.querySelector(`[data-field="${f}"]`).getAttribute('aria-invalid')).toBe('true');
    }
    expect(document.activeElement).toBe(container.querySelector('[data-field="student_id"]'));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(mockTrack).toHaveBeenCalledWith('apply', 'submit_blocked', 'missing_field');
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('typing in a field clears its marker', async () => {
    const { container } = render(<ApplicantPortal />);
    await screen.findByText('Chairperson');
    fireEvent.submit(form(container));
    await screen.findByRole('alert');
    fireEvent.change(screen.getByPlaceholderText(/Ayebale/), { target: { value: 'A' } });
    expect(container.querySelector('[data-field="full_name"]').getAttribute('aria-invalid')).toBeNull();
  });

  it('sends the registration number trimmed and in capitals', async () => {
    mockPost.mockImplementation((url) => Promise.resolve({ data: url === '/apply/upload-image' ? { secure_url: 'u' } : {} }));
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    fireEvent.submit(form(container));
    await screen.findByText(/Application Submitted/);
    const elig = mockPost.mock.calls.find(c => c[0] === '/apply/check-eligibility');
    expect(elig[1].student_id).toBe('22/U/IED/1086/GV');
    expect(mockPost.mock.calls.find(c => c[0] === '/apply')[1].student_id).toBe('22/U/IED/1086/GV');
  });
});

describe('B2: progress feedback', () => {
  it('A4: pressing Enter twice calls check-eligibility once', async () => {
    const d = deferred();
    mockPost.mockImplementation(() => d.promise);
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    fireEvent.submit(form(container));
    fireEvent.submit(form(container));
    expect(mockPost.mock.calls.filter(c => c[0] === '/apply/check-eligibility').length).toBe(1);
  });

  it('A7: while busy the fields are inert and the button is aria-busy; the step label shows', async () => {
    const d = deferred();
    mockPost.mockImplementation(() => d.promise);
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    fireEvent.submit(form(container));
    const btn = await screen.findByRole('button', { name: /Checking your details \(1\/3\)/ });
    expect(btn.getAttribute('aria-busy')).toBe('true');
    expect(screen.getByPlaceholderText(/Ayebale/).matches(':disabled')).toBe(true);
    expect(fileInputs(container)[0].matches(':disabled')).toBe(true);
    // choosing a position or method does nothing while busy
    const selected = (label) => screen.getByText(label).previousSibling.children.length > 0;   // the radio dot only exists when chosen
    expect(selected('Bank Transfer')).toBe(true);
    fireEvent.click(screen.getByText('Cash Receipt'));
    expect(selected('Cash Receipt')).toBe(false);
    expect(selected('Bank Transfer')).toBe(true);
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
  });

  it('shows upload percent and the 4-step label with a photo', async () => {
    const d = deferred();
    mockPost.mockImplementation((url, body, cfg) => {
      if (url === '/apply/check-eligibility') return Promise.resolve({ data: {} });
      cfg.onUploadProgress({ loaded: 5, total: 10 });
      return d.promise;
    });
    const { container } = render(<ApplicantPortal />);
    await fillAll(container, { photo: true });
    fireEvent.submit(form(container));
    expect(await screen.findByRole('button', { name: /Uploading photo \(2\/4\) 50%/ })).toBeTruthy();
  });

  it('warns before leaving only while uploading', async () => {
    const d = deferred();
    mockPost.mockImplementation(() => d.promise);
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    const idle = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(idle);
    expect(idle.defaultPrevented).toBe(false);
    fireEvent.submit(form(container));
    await screen.findByRole('button', { name: 'Cancel' });
    const busy = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(busy);
    expect(busy.defaultPrevented).toBe(true);
  });

  it('shows a slow-connection note on api:slow', async () => {
    mockPost.mockImplementation(() => new Promise(() => {}));
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    fireEvent.submit(form(container));
    await screen.findByRole('button', { name: 'Cancel' });
    expect(screen.queryByText(/Slow connection/)).toBeNull();
    act(() => { window.dispatchEvent(new CustomEvent('api:slow')); });
    expect(screen.getByText(/Slow connection/)).toBeTruthy();
  });

  it('Cancel aborts the request and nothing is submitted', async () => {
    let signal;
    mockPost.mockImplementation((url, body, cfg) => {
      signal = cfg.signal;
      return new Promise((_, rej) => cfg.signal.addEventListener('abort', () => rej({ code: 'ERR_CANCELED' })));
    });
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    fireEvent.submit(form(container));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(await screen.findByText(/Cancelled. Nothing was submitted/)).toBeTruthy();
    expect(signal.aborted).toBe(true);
    expect(screen.getByRole('button', { name: 'Submit Application' }).disabled).toBe(false);
  });

  it('maps a network failure to guidance', async () => {
    mockPost.mockRejectedValue({});
    const { container } = render(<ApplicantPortal />);
    await fillAll(container);
    fireEvent.submit(form(container));
    expect(await screen.findByText(/Check your connection/)).toBeTruthy();
  });
});

describe('B3: reuse uploads and draft restore', () => {
  it('A6: photo uploads once in total, receipt twice, when the receipt fails first', async () => {
    let receiptTries = 0;
    mockPost.mockImplementation((url, body) => {
      if (url === '/apply/upload-image') {
        const name = body.get('file').name;
        calls.push(name);
        if (name === 'receipt.jpg' && ++receiptTries === 1) return Promise.reject({ response: { status: 502, data: { detail: 'Image upload failed.' } } });
        return Promise.resolve({ data: { secure_url: `https://x/${name}` } });
      }
      return Promise.resolve({ data: {} });
    });
    const { container } = render(<ApplicantPortal />);
    await fillAll(container, { photo: true });
    fireEvent.submit(form(container));
    expect(await screen.findByText(/upload service is busy/)).toBeTruthy();
    fireEvent.submit(form(container));
    await screen.findByText(/Application Submitted/);
    expect(calls.filter(n => n === 'face.jpg').length).toBe(1);
    expect(calls.filter(n => n === 'receipt.jpg').length).toBe(2);
    const sent = mockPost.mock.calls.find(c => c[0] === '/apply')[1];
    expect(sent.image_url).toBe('https://x/face.jpg');
    expect(sent.payment_proof_url).toBe('https://x/receipt.jpg');
  });

  it('A8: a restored draft tells the applicant to re-attach the receipt', async () => {
    saveDraft('apply', { student_id: '22/u/x', full_name: 'A B', position_id: '', manifesto: '', payment_method: 'Bank Transfer' });
    render(<ApplicantPortal />);
    expect(await screen.findByText(/Re-attach your receipt/)).toBeTruthy();
  });

  it('A8b: no draft means no re-attach note', async () => {
    render(<ApplicantPortal />);
    await screen.findByText('Chairperson');
    expect(screen.queryByText(/Re-attach your receipt/)).toBeNull();
  });
});
