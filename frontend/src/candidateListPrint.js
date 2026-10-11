// Print rules for the Official List of Candidates: one A4 portrait sheet per page. Shared by the real list
// (CandidateListBlock) and the Superadmin's sample (CandidateListSample), so they print identically.
export const PRINT_CSS = `
  @media print {
    @page { size: A4 portrait; margin: 0; }
    body[data-printing="candidate-list"] .cl-other { display: none !important; }
    .cl-fit { width: 210mm !important; height: 297mm !important; max-width: none !important; margin: 0 !important; overflow: hidden !important; break-after: page; page-break-after: always; }
    .cl-fit.cl-last { break-after: auto; page-break-after: auto; }
    .cl-fit-in { transform: none !important; }
    .cl-sheets { padding: 0 !important; }
    .cl-sample { padding: 0 !important; background: #fff !important; min-height: 0 !important; }
    /* Page breaks are ignored inside fixed-height or scrolling ancestors, so flatten them for print. */
    html, body, #root { height: auto !important; min-height: 0 !important; overflow: visible !important; background: #fff !important; }
  }
`;
