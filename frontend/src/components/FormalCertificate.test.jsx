import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { FormalCertificateSheet, OrgSeal } from './FormalCertificate';
import { SampleCertificateDoc } from './CandidateStatusPortal';

const branding = { org_name: 'Kyambogo University Engineering Society', university_name: 'Kyambogo University', primary_color: '#003366', accent_color: '#f1c40f', logo_url: '', university_logo_url: '' };

describe('Formal digital seal certificate', () => {
  afterEach(() => { cleanup(); document.head.querySelectorAll('style').forEach((n) => n.remove()); });

  it('writes the organisation name around the seal and has no signature lines', () => {
    const { container } = render(<FormalCertificateSheet name="jane namukasa" position="general secretary" branding={branding}
      certificateId="CERT-ABC123" issuedAt="2026-10-11T08:00:00Z" issuedLabel="11 Oct 2026, 08:00" verifyUrl="https://x.test/verify/CERT-ABC123" />);
    expect(screen.getByText('Certificate of Nomination')).toBeTruthy();
    expect(screen.getByText('Jane Namukasa')).toBeTruthy();
    expect(container.querySelector('textPath').textContent).toContain('KYAMBOGO UNIVERSITY ENGINEERING SOCIETY');
    expect(screen.getByText(/ID: CERT-ABC123/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/signator/i);
  });

  it('repeats a short organisation name to fill the ring and shrinks a very long one', () => {
    const short = render(<OrgSeal orgName="ASSK" issued="" ink="#003366" accent="#b8860b" />);
    expect((short.container.querySelector('textPath').textContent.match(/ASSK/g) || []).length).toBeGreaterThan(1);
    cleanup();
    const long = render(<OrgSeal orgName={'Very Long Organisation Name '.repeat(5)} issued="" ink="#003366" accent="#b8860b" />);
    expect(Number(long.container.querySelector('text').getAttribute('font-size'))).toBeLessThan(10);
  });

  it('sample print: formal opens landscape with a SAMPLE mark, classic does not', () => {
    const formal = render(<SampleCertificateDoc template="formal" branding={branding} onClose={() => {}} />);
    expect(screen.getByText('SAMPLE')).toBeTruthy();
    expect([...document.querySelectorAll('style')].some((n) => n.textContent.includes('size: A4 landscape'))).toBe(true);
    expect(document.title).toBe('Jane Namukasa - Certificate of Nomination (Sample) - Kyambogo University Engineering Society');
    formal.unmount();
    render(<SampleCertificateDoc template="classic" branding={branding} onClose={() => {}} />);
    expect([...document.querySelectorAll('style')].some((n) => n.textContent.includes('size: A4 landscape'))).toBe(false);
  });
});
