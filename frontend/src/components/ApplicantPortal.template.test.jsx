import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) } }));
vi.mock('../analytics', () => ({ trackStep: () => {} }));
vi.mock('../paymentInfo', () => ({ usePaymentInfo: () => null }));
vi.mock('../hooks/usePolling', () => ({ default: () => {} }));
vi.mock('../context/HelpMenuContext', () => ({ useHelpMenu: () => ({ openFees: () => {} }) }));
vi.mock('./MobileMoneyNumber', () => ({ default: () => null }));

import ApplicantPortal from './ApplicantPortal';
import { resetBootstrapCache } from '../bootstrap';

const POSITIONS = [
  { _id: 'p1', title: 'Chairperson', description: 'Leads the society', application_fee: 50000 },
  { _id: 'p2', title: 'Treasurer', application_fee: 0 },
];
const STATUS = { approval_policy: 'majority_total' };
const file = (name) => new File(['x'], name, { type: 'image/jpeg', lastModified: 1 });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
URL.createObjectURL = URL.createObjectURL || (() => 'blob:x');

beforeEach(() => {
  cleanup(); mockGet.mockReset(); mockPost.mockReset(); resetBootstrapCache();
  sessionStorage.clear(); localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  mockGet.mockImplementation((url) => Promise.resolve({
    data: url === '/public/bootstrap' ? { branding: {}, status: STATUS, positions: POSITIONS }
      : url === '/positions' ? POSITIONS : STATUS,
  }));
});
afterEach(restoreTemplate);

const fileInputs = (c) => c.querySelectorAll('input[type=file]');
const form = (c) => c.querySelector('form');
const attrs = (c, a) => [...c.querySelectorAll(`[${a}]`)].map((e) => e.getAttribute(a));

async function open() {
  const out = render(<ApplicantPortal />);
  await screen.findByText('Chairperson');
  return out;
}
async function fillAll(c, { photo = false } = {}) {
  fireEvent.change(screen.getByPlaceholderText(/23\/U\/BCS/), { target: { value: '22/U/IED/1086/GV' } });
  fireEvent.change(screen.getByPlaceholderText(/Ayebale/), { target: { value: 'Ayebale Elizabeth' } });
  fireEvent.click(screen.getByText('Chairperson'));
  fireEvent.change(screen.getByPlaceholderText(/I am running/), { target: { value: 'Vote for me' } });
  fireEvent.click(screen.getByText('Bank Transfer'));
  fireEvent.change(fileInputs(c)[0], { target: { files: [file('receipt.jpg')] } });
  if (photo) fireEvent.change(fileInputs(c)[1], { target: { files: [file('face.jpg')] } });
}

describe('ApplicantPortal template seam (BP-T6)', () => {
  it('default render has no bp- class and no data-template', async () => {
    useDefault();
    const { container } = await open();
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('[id^="apply-"]')).toBeNull();   // ids and htmlFor exist only in the template
  });

  it('same visible text, data-field and data-track under both templates', async () => {
    useDefault();
    const a = await open();
    const def = { text: a.container.textContent, fields: attrs(a.container, 'data-field'), tracks: attrs(a.container, 'data-track') };
    cleanup();
    await useBlueprint();
    const b = await open();
    expect(b.container.textContent).toBe(def.text);
    expect(attrs(b.container, 'data-field')).toEqual(def.fields);
    expect(attrs(b.container, 'data-track')).toEqual(def.tracks);
    expect(def.fields).toEqual(['student_id', 'full_name', 'position_id', 'manifesto', 'payment_method', 'payment_proof']);
    expect(def.tracks).toContain('apply-submit');
  });

  it('blueprint uses the template classes on the form', async () => {
    await useBlueprint();
    const { container } = await open();
    expect(container.querySelectorAll('.bp-card').length).toBe(6);       // details, position, manifesto, payment, photo, submit
  });

  it('blueprint: fields are labelled and use bp-in', async () => {
    await useBlueprint();
    const { container } = await open();
    expect(screen.getByLabelText(/Student Registration Number/).className).toContain('bp-in');
    expect(screen.getByLabelText(/Full Name \(as on your student ID\)/).className).toContain('bp-in');
    expect(screen.getByRole('textbox', { name: /Your Manifesto/ })).toBe(container.querySelector('[data-field="manifesto"]'));
    expect(container.querySelector('[data-field="manifesto"]').className).toContain('bp-in');
  });

  it('an empty submit gives the same message and marks the same fields in both templates', async () => {
    useDefault();
    const a = await open();
    fireEvent.submit(form(a.container));
    const defAlert = (await screen.findByRole('alert')).textContent;
    const defInvalid = [...a.container.querySelectorAll('[aria-invalid="true"]')].map((e) => e.getAttribute('data-field'));
    cleanup();
    await useBlueprint();
    const b = await open();
    fireEvent.submit(form(b.container));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(defAlert);
    expect(alert.className).toContain('bp-alt');
    expect([...b.container.querySelectorAll('[aria-invalid="true"]')].map((e) => e.getAttribute('data-field'))).toEqual(defInvalid);
    expect(defInvalid.length).toBe(6);
    expect(document.activeElement).toBe(b.container.querySelector('[data-field="student_id"]'));
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('blueprint: choosing a position / method marks exactly one row with the tick and bp-on', async () => {
    await useBlueprint();
    const { container } = await open();
    const rows = (group) => [...container.querySelector(`[data-field="${group}"]`).children];
    fireEvent.click(screen.getByText('Treasurer'));
    expect(rows('position_id').map((r) => r.classList.contains('bp-on'))).toEqual([false, true]);
    expect(rows('position_id').map((r) => r.querySelector('.bp-tick').children.length)).toEqual([0, 1]);
    fireEvent.click(screen.getByText('Chairperson'));
    expect(rows('position_id').map((r) => r.classList.contains('bp-on'))).toEqual([true, false]);
    fireEvent.click(screen.getByText('Cash Receipt'));
    const pay = rows('payment_method');
    expect(pay.filter((r) => r.classList.contains('bp-on')).length).toBe(1);
    expect(pay[3].classList.contains('bp-on')).toBe(true);
    expect(screen.getByText('Cash Receipt').previousSibling.children.length).toBe(1);   // same "child only when chosen" shape as the default dot
  });

  it('StepBar: absent at rest, filled to the current step during a submit, gone afterwards', async () => {
    await useBlueprint();
    const d = deferred();
    mockPost.mockImplementation((url) => (url === '/apply/check-eligibility' ? d.promise : Promise.resolve({ data: { secure_url: 'u' } })));
    const { container } = await open();
    expect(container.querySelector('.bp-steps')).toBeNull();
    await fillAll(container);
    fireEvent.submit(form(container));
    await screen.findByRole('button', { name: /Checking your details \(1\/3\)/ });
    const bar = container.querySelector('.bp-steps');
    expect(bar.getAttribute('aria-hidden')).toBe('true');
    expect(bar.children.length).toBe(3);                       // no photo: 3 steps, as in stepLabel
    expect([...bar.children].map((i) => i.classList.contains('bp-on'))).toEqual([true, false, false]);
    d.resolve({ data: {} });
    await screen.findByText(/Application Submitted/);
    expect(container.querySelector('.bp-steps')).toBeNull();
  });

  it('StepBar has 4 segments when a photo is attached', async () => {
    await useBlueprint();
    const d = deferred();
    mockPost.mockImplementation(() => d.promise);
    const { container } = await open();
    await fillAll(container, { photo: true });
    fireEvent.submit(form(container));
    await screen.findByRole('button', { name: /Checking your details \(1\/4\)/ });
    expect(container.querySelector('.bp-steps').children.length).toBe(4);
  });

  it('default render never shows a StepBar during a submit', async () => {
    useDefault();
    const d = deferred();
    mockPost.mockImplementation(() => d.promise);
    const { container } = await open();
    await fillAll(container);
    fireEvent.submit(form(container));
    await screen.findByRole('button', { name: /Checking your details/ });
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
  });

  it('success view: same text in both templates; template classes only in blueprint', async () => {
    const submit = async () => {
      mockPost.mockImplementation((url) => Promise.resolve({ data: url === '/apply/upload-image' ? { secure_url: 'u' } : {} }));
      const out = await open();
      await fillAll(out.container);
      fireEvent.submit(form(out.container));
      await screen.findByText(/Application Submitted/);
      return out;
    };
    useDefault();
    const a = await submit();
    const defText = a.container.textContent;
    expect(a.container.querySelector('[class*="bp-"]')).toBeNull();
    cleanup();
    await useBlueprint();
    const b = await submit();
    expect(b.container.textContent).toBe(defText);
    expect(b.container.querySelector('.bp-card.bp-done')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Submit Another Application' }).className).toContain('bp-btn');
  });

  it('submit button keeps its label, data-track and busy state in blueprint', async () => {
    await useBlueprint();
    const { container } = await open();
    const btn = screen.getByRole('button', { name: 'Submit Application' });
    expect(btn.getAttribute('data-track')).toBe('apply-submit');
    expect(btn.className).toContain('bp-btn');
    expect(container.querySelector('input[data-field="student_id"]').getAttribute('style')).toBeNull();   // inline look dropped, class decides
  });
});
