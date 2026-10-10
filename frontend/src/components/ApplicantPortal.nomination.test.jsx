import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ApplicantPortal from './ApplicantPortal';
const mockGet = vi.fn(); const mockPost = vi.fn();
vi.mock('../api', () => ({ default: { get:(...a)=>mockGet(...a), post:(...a)=>mockPost(...a) } }));
vi.mock('../paymentInfo', () => ({ usePaymentInfo:()=>null }));
vi.mock('../hooks/usePolling', () => ({ default: () => {}, startPolling: () => () => {} }));
vi.mock('../analytics', () => ({ trackStep:()=>{} }));
vi.mock('../context/HelpMenuContext', () => ({ useHelpMenu:()=>({ openFees:()=>{} }) }));
vi.mock('./MobileMoneyNumber', () => ({ default:()=>null }));
vi.mock('../session', () => ({ loadDraft:()=>null, saveDraft:()=>{}, clearDraft:()=>{} }));
vi.mock('../bootstrap', () => ({ fetchBootstrap:()=>Promise.resolve({ positions:[{_id:'p1',title:'President',application_fee:0}], status:{ approval_policy:'majority_total' }}) }));
describe('ApplicantPortal nomination form', () => {
  beforeEach(()=>{mockGet.mockReset(); mockPost.mockReset(); mockGet.mockImplementation(url => Promise.resolve({data: url==='/nomination-form' ? {enabled:true,required:true,title:'Signed nomination',instructions:'Fill it in\nSign it',template_file:{url:'https://example.invalid/form.pdf',filename:'form.pdf'},accepted_types:['pdf','docx'],max_mb:5} : {}}));});
  it('renders enabled form with download immediately after instructions', async()=>{ render(<ApplicantPortal/>); await screen.findByText('President'); const section=screen.getByText(/^Signed nomination/).closest('div'); expect(section.textContent).toContain('Fill it in'); expect(section.querySelector('a[data-track="apply-nomination-download"]')).not.toBeNull(); const p=section.querySelector('[data-track="apply-nomination-download"]'); expect(p.previousElementSibling?.textContent).toContain('Sign it'); });
  it('puts the nomination form first, right after the instructions and before Personal Details', async()=>{ const {container}=render(<ApplicantPortal/>); await screen.findByText('President'); const nom=screen.getByText(/^Signed nomination/); const personal=screen.getByText('Personal Details'); expect(nom.compareDocumentPosition(personal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); expect(container.textContent).toContain('Nomination Form:'); });
  it('blocks submit when required form is missing', async()=>{ const {container}=render(<ApplicantPortal/>); await screen.findByText('President'); fireEvent.submit(container.querySelector('form')); expect((await screen.findByRole('alert')).textContent).toContain('Signed nomination form'); });
});
