import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('qrcode', () => ({ default: { toDataURL: () => Promise.resolve('data:image/png;base64,AAAA') } }));
import SampleCandidateListDoc from './CandidateListSample';

describe('SampleCandidateListDoc', () => {
  it('shows a SAMPLE list in the chosen style, with the organisation name, and goes back', () => {
    const onClose = vi.fn();
    render(<SampleCandidateListDoc branding={{ org_name: 'KYUES', document_template: 'formal' }} onClose={onClose} />);
    expect(screen.getAllByText('SAMPLE').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Official List of Candidates/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Formal digital seal/)).toBeTruthy();
    fireEvent.click(screen.getByText(/Back/));
    expect(onClose).toHaveBeenCalled();
  });

  it('uses more pages with long names', () => {
    const { rerender } = render(<SampleCandidateListDoc branding={{}} onClose={() => {}} />);
    expect(screen.getByText(/· 1 page$/)).toBeTruthy();
    rerender(<SampleCandidateListDoc branding={{}} longNames onClose={() => {}} />);
    expect(screen.queryByText(/· 1 page$/)).toBeNull();
  });
});
