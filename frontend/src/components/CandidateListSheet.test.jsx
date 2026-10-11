import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CandidateListPage } from './CandidateListSheet';

const list = { list_id: 'LIST-ABC123', org_name: 'KYUES', issued_at: '2026-10-11T14:05:00Z', current: true, document_template: 'classic' };
const items = [{ position: 'Chairperson', continued: false, startIndex: 0, names: ['jane namukasa', 'Brian Okello'] }];
const props = { list, branding: {}, items, page: 2, total: 3, verifyUrl: 'https://x.org/verify-list/LIST-ABC123', qrDataUrl: 'data:image/png;base64,AAAA' };

describe('CandidateListPage', () => {
  it('carries the footer (QR, id, issue time) and the page count on every page, in both styles', () => {
    for (const document_template of ['classic', 'formal']) {
      const { unmount } = render(<CandidateListPage {...props} list={{ ...list, document_template }} />);
      expect(screen.getAllByText(/LIST-ABC123/).length).toBeGreaterThan(0);
      expect(screen.getByAltText('Verification QR code')).toBeTruthy();
      expect(screen.getByText(/Page 2 of 3/)).toBeTruthy();
      expect(screen.getByText(/Issued:/)).toBeTruthy();
      unmount();
    }
  });

  it('numbers names in the formal style and shows only names (no contacts)', () => {
    render(<CandidateListPage {...props} list={{ ...list, document_template: 'formal' }} />);
    expect(screen.getByText(/1\. Jane Namukasa/)).toBeTruthy();
    expect(screen.getByText(/2\. Brian Okello/)).toBeTruthy();
  });

  it('marks a superseded list on the page itself', () => {
    render(<CandidateListPage {...props} list={{ ...list, current: false, superseded_at: '2026-10-12T09:00:00Z' }} />);
    expect(screen.getByText('SUPERSEDED')).toBeTruthy();
  });
});
