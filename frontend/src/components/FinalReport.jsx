import React, { useMemo } from 'react';
import { Icon } from './icons.jsx';

// 1. Define the security "Look" for each stage
const securityConfig = {
  open: {
    label: "PRELIMINARY TALLY",
    texture: 'url("https://www.transparenttextures.com/patterns/diagonal-stripes.png")',
    ghostText: "DRAFT",
    color: "#64748b"
  },
  provisional: {
    label: "PROVISIONAL TABULATION",
    texture: 'url("https://www.transparenttextures.com/patterns/asfalt-dark.png")',
    ghostText: "UNDER REVIEW",
    color: "#f59e0b"
  },
  certified: {
    label: "OFFICIAL CERTIFIED RESULTS",
    texture: 'url("https://www.transparenttextures.com/patterns/cubes.png")',
    ghostText: "", // No ghost text for clean final copy
    color: "#3b82f6"
  }
};

const PrintStyles = () => (
  <style>{`
    @media print {
      .report-watermark {
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
        background-color: white !important;
      }
      /* Ensure text remains high-contrast black */
      .report-content {
        position: relative;
        z-index: 2;
      }
     .report-watermark h1:not(.print-color-keep),
     .report-watermark h2:not(.print-color-keep),
     .report-watermark h3:not(.print-color-keep),
     .report-watermark h4:not(.print-color-keep),
     .report-watermark p:not(.print-color-keep) {
       color: #000 !important;
     }
    }
  `}</style>
);


/*
 * PUBLIC results report.
 *
 * This component renders on the unauthenticated /results page, so it contains
 * only content that is public at every stage of the election: tallies,
 * turnout, the per-position breakdown, the certification status badge and the
 * participation roll.
 *
 * The sworn declaration, the signature grid and the cc distribution list used
 * to render here too, gated by a client-side `isCertified &&`. That was never
 * an access boundary — the text and layout shipped in the public JS bundle
 * regardless, so anyone with dev tools could reconstruct the signed document.
 * They now live only in OfficialCertificationBlock, which is fed by the
 * authenticated /admin/official-report endpoint.
 */
export default function FinalReport({
  data, totalVotes, isElectionOpen, isCertified, logoUrl,
  orgName = "the Organisation", universityName = "", universityLogoUrl = "",
  // Present only for the authenticated Official Document. Their presence, not
  // a separate "mode" flag, is what switches the footer from the public
  // disclaimer to the signed instrument — so a caller can never show
  // signatures without also having fetched the declaration they attach to.
  declaration = null, signatories = null, ccList = [],
}) {
  // Pick the active config
  const activeStage = isElectionOpen ? 'open' : (isCertified ? 'certified' : 'provisional');
  const config = securityConfig[activeStage];

  // Memoised so it isn't a fresh array identity on every render, which would
  // invalidate every downstream useMemo that depends on it.
  const results = useMemo(() => data?.results || [], [data]);

  const stripeColor = `${config.color}08`;

  // A rolling hash of whatever JSON happened to be on screen. It is a
  // copy-checksum for spotting two printouts that differ — nothing more. It
  // is NOT the cryptographic audit chain, so it is no longer labelled
  // "Verified Secure": the real chain hash is only available to authenticated
  // admins via /admin/official-report, because verifying it requires the
  // server to re-derive it from the raw ballot events.
  const reportFingerprint = useMemo(() => {
    const seed = JSON.stringify(results) + totalVotes + isElectionOpen + isCertified;
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
      hash = (hash << 5) - hash + seed.charCodeAt(i);
      hash |= 0; 
    }
    return Math.abs(hash).toString(16).toUpperCase();
  }, [results, totalVotes, isElectionOpen, isCertified]);

  const orderedPositions = useMemo(() => {
    const groups = [];
    results.forEach(candidate => {
      const posName = candidate.position || "Other";
      let group = groups.find(g => g.name === posName);
      if (!group) {
        group = { name: posName, candidates: [] };
        groups.push(group);
      }
      group.candidates.push(candidate);
    });
    return groups;
  }, [results]);

  if (!data || !data.results) {
    return null;
  }

  return (
  <>
    <PrintStyles />
    <div className="print-only report-watermark" style={{ 
      padding: '40px', 
      backgroundColor: '#fff', 
      minHeight: '100vh', 
      position: 'relative',
      // This creates the actual colored stripes
      backgroundImage: `linear-gradient(45deg, ${stripeColor} 25%, transparent 25%, transparent 50%, ${stripeColor} 50%, ${stripeColor} 75%, transparent 75%, transparent 100%)`,
      backgroundSize: '80px 80px',
      borderLeft: `15px solid ${config.color}`, // The solid color distinction bar
      WebkitPrintColorAdjust: 'exact',
      printColorAdjust: 'exact',
    }}>
      
      {/* BIG FLOATING GHOST TEXT (Anti-Forgery) */}
      {config.ghostText && (
        <div style={{
          position: 'absolute', top: '50%', left: '50%', 
          transform: 'translate(-50%, -50%) rotate(-45deg)',
          fontSize: '120px', fontWeight: '900', color: 'rgba(0,0,0,0.04)', 
          pointerEvents: 'none', zIndex: 0, whiteSpace: 'nowrap'
        }}>
          {config.ghostText}
        </div>
      )}
      
      {/* HEADER WITH DUAL LOGOS.

          The QR code that used to sit here encoded window.location.href and
          was rendered by fetching an image from a third-party QR service —
          which both leaked the viewer's exact URL to that service and made
          the printed report depend on a network call at print time. It said
          "SCAN TO VERIFY" while verifying nothing. */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '30px',
        position: 'relative',
        zIndex: 1,
        gap: '12px',
      }}>

        {/* Left: University logo */}
        <div style={{ width: '100px', textAlign: 'left', flexShrink: 0 }}>
          {universityLogoUrl && (
            <img src={universityLogoUrl} alt="University logo" style={{ width: '80px', height: 'auto' }} />
          )}
        </div>

        {/* Center: Title */}
        <div style={{ textAlign: 'center', flex: 1, padding: '0 10px', minWidth: 0 }}>
          <h1 style={{ margin: '0', fontSize: '22px', textTransform: 'uppercase', fontWeight: '900' }}>
            {universityName}
          </h1>
          <h2 style={{ margin: '2px 0', fontSize: '18px', color: '#1e293b', fontWeight: 'bold' }}>
            {orgName}
          </h2>
          <h3 style={{ margin: '5px 0', fontSize: '16px', fontWeight: '500' }}>
            Public Election Results Report
          </h3>
        </div>

        {/* Right: Organisation logo */}
        <div style={{ width: '100px', textAlign: 'right', flexShrink: 0 }}>
          {logoUrl && (
            <img src={logoUrl} alt="Organisation logo" style={{ width: '70px', height: 'auto' }} />
          )}
        </div>
      </div>

      {/* METADATA */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px', borderBottom: `2px solid ${config.color}`, paddingBottom: '10px', position: 'relative', zIndex: 1 }}>
        <div>
          <p style={{ margin: '2px 0', fontSize: '12px' }}><strong>Status:</strong> <span style={{color: config.color}}>{config.label}</span></p>
          <p style={{ margin: '2px 0', fontSize: '12px' }}><strong>Voter Participation:</strong> {totalVotes} Students</p>
          <p className="print-color-keep" style={{ margin: '2px 0', fontSize: '10px', color: '#666' }}><strong>Copy checksum:</strong> {reportFingerprint}</p>
        </div>
        <div style={{ textAlign: 'right', fontSize: '12px' }}>
          <p style={{ margin: '2px 0' }}><strong>Date Generated:</strong> {new Date().toLocaleDateString()}</p>
          <p style={{ margin: '2px 0' }}><strong>Timestamp:</strong> {new Date().toLocaleTimeString()}</p>
        </div>
      </div>

        {/* The sworn Official Declaration that used to render here has moved
            to the admin-only OfficialCertificationBlock. A public visitor sees
            the certification STATUS (a fact) but not the signed legal
            instrument. */}
        <div style={certStatusStyle}>
          <strong>Certification status:</strong>{' '}
          {isElectionOpen
            ? 'Voting is still open — these figures are a live tally.'
            : (isCertified
                ? 'Results have been certified by the Electoral Commission.'
                : 'Voting is closed. Results are provisional, pending certification.')}
        </div>

        {/* Signed declaration — only ever passed in by the authenticated
            OfficialCertificationBlock. Sits ahead of the tallies, same as
            the printed copy in the reference PDF. */}
        {declaration && (
          <div style={declarationBoxStyle} className="declaration-block">
            <h4 style={{ textAlign: 'center', textDecoration: 'underline', fontSize: '14px', position: 'relative', zIndex: 1 }}>
              OFFICIAL DECLARATION OF {String(orgName).toUpperCase()} ELECTION RESULTS
            </h4>
            <p style={{ fontSize: '13px', textAlign: 'justify', lineHeight: 1.6, position: 'relative', zIndex: 1 }}>
              {declaration}
            </p>
          </div>
        )}

      {/* EXECUTIVE SUMMARY */}
      {!isElectionOpen && (
        <div style={{ marginBottom: '30px', breakInside: 'avoid', position: 'relative', zIndex: 1 }}>
          <h3 className="print-color-keep" style={{ borderBottom: `2px solid ${config.color}`, color: config.color, paddingBottom: '5px', fontSize: '16px' }}>
            Executive Summary: Elected Officials
          </h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '10px' }}>
            <thead>
              <tr style={{ backgroundColor: config.color, color: '#fff' }}>
                <th style={summaryHeaderStyle}>Position</th>
                <th style={summaryHeaderStyle}>Elected Official</th>
                <th style={summaryHeaderStyle}>Final Votes</th>
              </tr>
            </thead>
            <tbody>
              
              {orderedPositions.map((pos) => {
                const isSolo = pos.candidates.length === 1;
                const sorted = [...pos.candidates].sort((a, b) => b.votes - a.votes);
                const topCandidate = sorted[0];
                const secondCandidate = sorted[1];
                
                const isTie = !isSolo && topCandidate?.votes > 0 && topCandidate?.votes === secondCandidate?.votes;
                
                // LOGIC CHANGE HERE:
                const hasMandate = isSolo && topCandidate?.votes >= 100;
                const isElected = !isTie && (isSolo ? hasMandate : (topCandidate?.votes > 0));
              
                let resultText = topCandidate?.name || "N/A";
                
                if (isTie) {
                    resultText = "TIE: RE-RUN REQ.";
                } else if (isSolo && hasMandate) {
                    // Show both name and status for unopposed winners
                    resultText = `${topCandidate.name} (MANDATE GAINED)`;
                } else if (!isElected) {
                    resultText = isSolo ? "UNDERMANDATED" : "NO WINNER";
                }
              
                return (
                  <tr key={pos.name}>
                    <td style={summaryCellStyle}><strong>{pos.name}</strong></td>
                    <td style={{ 
                      ...summaryCellStyle, 
                      color: isElected ? (isSolo ? '#10b981' : '#000') : (isTie ? '#e67e22' : '#ef4444'),
                      fontWeight: isSolo && hasMandate ? 'bold' : 'normal'
                    }}>
                      {resultText}
                    </td>
                    <td style={summaryCellStyle}>{topCandidate?.votes || 0}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )} {/* <--- THIS CLOSES THE EXECUTIVE SUMMARY BLOCK */}

      {/* DETAILED RESULTS SECTION */}
      <h3 style={{ fontSize: '14px', textDecoration: 'underline', marginBottom: '10px', position: 'relative', zIndex: 1 }}>Detailed Tally Results</h3>
      {orderedPositions.map((pos) => {
        const sortedCandidates = [...pos.candidates].sort((a, b) => b.votes - a.votes);
        const maxVotes = sortedCandidates[0]?.votes || 0;
        const totalVotesForPos = pos.candidates.reduce((acc, curr) => acc + curr.votes, 0);

        return (
          <div key={pos.name} style={{ marginBottom: '25px', breakInside: 'avoid', position: 'relative', zIndex: 1 }}>
            <h4 style={posHeaderStyle}>Position: {pos.name}</h4>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ backgroundColor: '#fafafa' }}>
                  <th style={tableHeaderStyle}>Candidate</th>
                  <th style={tableHeaderStyle}>Votes</th>
                  <th style={tableHeaderStyle}>Share</th>
                  <th style={tableHeaderStyle}>Status</th>
                </tr>
              </thead>
              <tbody>
               
                {sortedCandidates.map((c, i) => {
                  const isSolo = pos.candidates.length === 1;
                  const share = totalVotesForPos > 0 ? ((c.votes / totalVotesForPos) * 100).toFixed(1) : 0;
                  const isPartOfTie = !isSolo && c.votes === maxVotes && maxVotes > 0 && pos.candidates.filter(can => can.votes === maxVotes).length > 1;
                  
                  // LOGIC CHANGE HERE:
                  const hasMandate = isSolo && c.votes >= 100;
                  const isWinner = !isElectionOpen && c.votes === maxVotes && maxVotes > 0 && !isPartOfTie && (!isSolo || hasMandate);
                
                  return (
                    <tr key={i}>
                      <td style={tableCellStyle}>
                        {isWinner ? (isSolo ? <><Icon name="success" /> {c.name}</> : <><Icon name="trophy" /> {c.name}</>) : (isPartOfTie ? <><Icon name="scale" /> {c.name}</> : c.name)}
                      </td>
                      <td style={{ ...tableCellStyle, textAlign: 'center' }}>{c.votes}</td>
                      <td style={{ ...tableCellStyle, textAlign: 'center' }}>{share}%</td>
                      <td style={{ 
                        ...tableCellStyle, 
                        textAlign: 'center', 
                        fontWeight: 'bold', 
                        color: isWinner && isSolo ? '#10b981' : (isPartOfTie ? '#e67e22' : '#000') 
                      }}>
                        {isWinner ? (isSolo ? "MANDATE GAINED" : "ELECTED") : (isPartOfTie ? "TIE" : (isSolo && !hasMandate && !isElectionOpen ? "UNDERMANDATED" : "-"))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}

      {/* MANDATE EXPLANATION FOOTNOTE */}
      <div style={{ marginTop: '-15px', marginBottom: '30px', padding: '10px', border: '1px solid #ddd', backgroundColor: '#f9f9f9', breakInside: 'avoid', position: 'relative', zIndex: 1 }}>
        <p style={{ margin: 0, fontSize: '9px', color: '#444', lineHeight: '1.4' }}>
          <strong>Note on Minimum Mandate:</strong> In accordance with the {orgName} Election Guidelines, 
          candidates running unopposed (solo) in any position must secure a minimum of <strong>100 valid votes</strong> 
           to be declared constitutionally elected. Failure to meet this threshold results in an 'Undermandated' 
           status, requiring a by-election or appointment per union bylaws.
        </p>
      </div>

     
      {signatories ? (
        <>
          <div style={signatureGridStyle} className="signature-grid">
            {signatories.map((s, i) => (
              <div key={`${s.full_name}-${i}`}>
                <p style={{ fontWeight: 'bold', margin: 0, fontSize: '13px' }}>{s.full_name || '\u00a0'}</p>
                <p style={{ fontSize: '11px', margin: 0, fontStyle: 'italic', opacity: 0.8 }}>{s.role}</p>
                <div style={{ borderTop: '1px solid currentColor', marginTop: '26px' }} />
              </div>
            ))}
          </div>
          {ccList?.length > 0 && (
            <div style={{ marginTop: '22px', fontSize: '11px', borderTop: '1px solid currentColor', paddingTop: '10px', position: 'relative', zIndex: 1 }}>
              {ccList.map((c, i) => <div key={i}>Cc: {c}</div>)}
            </div>
          )}
        </>
      ) : (
        /* Public copy only: the signed declaration and signature page are
           issued separately by the Electoral Commission. */
        <div style={{ marginTop: '30px', fontSize: '10px', borderTop: '1px solid #000', paddingTop: '10px', position: 'relative', zIndex: 1 }}>
          <p style={{ margin: 0 }}>
            This is the public results record for {orgName}. The signed declaration and
            signature page are issued separately by the Electoral Commission and are not
            part of this document.
          </p>
        </div>
      )}

      {/* FOOTER STAMP */}
      <div style={{ textAlign: 'center', marginTop: '60px', borderTop: `1px dashed ${config.color}`, paddingTop: '20px', position: 'relative', zIndex: 1 }}>
        <p className="print-color-keep" style={{ letterSpacing: '8px', fontWeight: '900', color: config.color, fontSize: '12px' }}>
          *** END OF {activeStage.toUpperCase()} REPORT ***
        </p>
        <p className="print-color-keep" style={{ fontSize: '9px', color: '#aaa' }}>Copy checksum: {reportFingerprint} | Mode: {activeStage.toUpperCase()}</p>
      </div>
    </div>
  </>
  );
}

// Styles
const declarationBoxStyle = { border: '2px solid currentColor', padding: '20px', marginBottom: '20px', fontFamily: '"Times New Roman", Times, serif', position: 'relative', zIndex: 1 };
const signatureGridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '26px', marginTop: '30px', position: 'relative', zIndex: 1 };
const certStatusStyle = {
  border: '1px solid #000',
  padding: '12px',
  marginBottom: '24px',
  fontSize: '12px',
  position: 'relative',
  zIndex: 1,
  breakInside: 'avoid',
};




const summaryHeaderStyle = { padding: '8px', border: '1px solid #3b82f6', textAlign: 'left', fontSize: '11px' };
const summaryCellStyle = { padding: '8px', border: '1px solid #ddd', fontSize: '11px' };
const tableHeaderStyle = { padding: '8px', border: '1px solid #000', textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' };
const tableCellStyle = { padding: '8px', border: '1px solid #000', fontSize: '11px' };
const posHeaderStyle = { backgroundColor: '#f2f2f2', padding: '6px', fontSize: '12px', border: '1px solid #000', margin: '0', fontWeight: 'bold' };
