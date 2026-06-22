import React, { useMemo } from 'react';

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

const shuffleArray = (array) => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

export default function FinalReport({ data, totalVotes, isElectionOpen, isCertified }) {
  if (!data || !data.results) {
    return null; 
  }

  // Pick the active config
  const activeStage = isElectionOpen ? 'open' : (isCertified ? 'certified' : 'provisional');
  const config = securityConfig[activeStage];

  const LOGO_URL = "https://res.cloudinary.com/dyn2729ou/image/upload/v1773050338/IMG-20260307-WA0117-removebg-preview_ou65sh.png"; 
  const PRIVACY_THRESHOLD = 50; 
  const results = data.results || [];
  
  const shuffledVoterRoll = useMemo(() => {
    return shuffleArray(data.voter_roll || []);
  }, [data.voter_roll]);

  const stripeColor = `${config.color}08`;

  const reportFingerprint = useMemo(() => {
    // Added isCertified to seed to ensure ID changes upon certification
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
    }
  `}</style>
);

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
      
               {/* HEADER WITH DUAL LOGOS & QR VERIFICATION */}
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center', // Changed to center for better logo alignment
            marginBottom: '30px', 
            position: 'relative', 
            zIndex: 1 
          }}>
            
            {/* Left: Kyambogo University Logo */}
            <div style={{ width: '100px', textAlign: 'left' }}>
              <img 
                src="https://res.cloudinary.com/dyn2729ou/image/upload/v1773467221/3a635ea3e25d45fca31a6b06490aa4b7_zdmuza.jpg" // <--- Replace with Kyambogo University Logo URL
                alt="KYU Logo" 
                style={{ width: '80px', height: 'auto' }} 
              />
            </div>
          
            {/* Center: Title Text */}
            <div style={{ textAlign: 'center', flex: 1, padding: '0 20px' }}>
              <h1 style={{ margin: '0', fontSize: '22px', textTransform: 'uppercase', fontWeight: '900' }}>
                Kyambogo University
              </h1>
              <h2 style={{ margin: '2px 0', fontSize: '18px', color: '#1e293b', fontWeight: 'bold' }}>
                Course Coordinators Union (KYUCCU)
              </h2>
              <h3 style={{ margin: '5px 0', fontSize: '16px', fontWeight: '500' }}>
                Official Election Report 2026/2027
              </h3>
              <p style={{ color: '#64748b', fontSize: '11px', margin: '0' }}>
                "Service, Integrity, and Leadership"
              </p>
            </div>
          
            {/* Right: Union Logo + QR Code */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100px', gap: '10px' }}>
              <img 
                src={LOGO_URL} 
                alt="Union Logo" 
                style={{ width: '70px', height: 'auto' }} 
              />
              <div style={{ textAlign: 'center' }}>
                <img 
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=${encodeURIComponent(window.location.href)}`} 
                  alt="Verify" 
                  style={{ width: '50px', border: '1px solid #eee' }} 
                />
                <p style={{ fontSize: '7px', marginTop: '2px', fontWeight: 'bold', lineHeight: '1' }}>
                  SCAN TO<br/>VERIFY
                </p>
              </div>
            </div>
          </div>

      {/* METADATA */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px', borderBottom: `2px solid ${config.color}`, paddingBottom: '10px', position: 'relative', zIndex: 1 }}>
        <div>
          <p style={{ margin: '2px 0', fontSize: '12px' }}><strong>Status:</strong> <span style={{color: config.color}}>{config.label}</span></p>
          <p style={{ margin: '2px 0', fontSize: '12px' }}><strong>Voter Participation:</strong> {totalVotes} Students</p>
          <p style={{ margin: '2px 0', fontSize: '10px', color: '#666' }}><strong>Fingerprint:</strong> {reportFingerprint}</p>
        </div>
        <div style={{ textAlign: 'right', fontSize: '12px' }}>
          <p style={{ margin: '2px 0' }}><strong>Date Generated:</strong> {new Date().toLocaleDateString()}</p>
          <p style={{ margin: '2px 0' }}><strong>Timestamp:</strong> {new Date().toLocaleTimeString()}</p>
        </div>
      </div>

        {/* --- NEW: OFFICIAL DECLARATION SECTION (Only shows when Certified) --- */}
        {isCertified && (
          <div style={declarationContainerStyle}>
            <div style={{ textAlign: 'center', marginBottom: '20px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 'bold', textDecoration: 'underline', margin: '0' }}>
                OFFICIAL DECLARATION OF KYUCCU ELECTION RESULTS
              </h3>
            </div>
        
            <div style={declarationBodyStyle}>
              <p>
                I, <strong>Ajuna Christian</strong>, the duly appointed KYUCCU Electoral Commissioner, 
                hereby declare that the KYUCCU elections conducted on <strong>13th March 2026</strong> through 
                the official online voting portal were carried out in accordance with the KYUCCU electoral guidelines and procedures.
              </p>
              <p style={{ marginTop: '10px' }}>
                After the close of voting and the verification and tallying of all valid votes cast, 
                I hereby officially declare the successful candidates listed in the summary below as the 
                duly elected leaders of the Kyambogo University Course Coordinators' Union (KYUCCU) for the 2026/2027 term.
              </p>
              <p style={{ marginTop: '10px' }}>
                I congratulate the successful candidates and extend appreciation to all aspirants, 
                coordinators, and voters for participating and upholding the principles of a free, 
                fair, and transparent election.
              </p>
            </div>

           
            
        
{/* EXECUTIVE SUMMARY */}
      {!isElectionOpen && (
        <div style={{ marginBottom: '30px', breakInside: 'avoid', position: 'relative', zIndex: 1 }}>
          <h3 style={{ borderBottom: `2px solid ${config.color}`, color: config.color, paddingBottom: '5px', fontSize: '16px' }}>
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
                        {isWinner ? (isSolo ? `✅ ${c.name}` : `🏆 ${c.name}`) : (isPartOfTie ? `⚖️ ${c.name}` : c.name)}
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
          <strong>Note on Minimum Mandate:</strong> In accordance with the KYUCCU Election Guidelines 2026, 
          candidates running unopposed (solo) in any position must secure a minimum of <strong>100 valid votes</strong> 
           to be declared constitutionally elected. Failure to meet this threshold results in an 'Undermandated' 
           status, requiring a by-election or appointment per union bylaws.
        </p>
      </div>

     
        {/* --- SIGNATURE GRID --- */}
        <div style={signatureGrid}>
          <div>
            <p style={signName}>Ajuna Christian</p>
            <p style={signTitle}>Chairperson EC</p>
            <div style={signLine}></div>
          </div>
          <div>
            <p style={signName}>Mwanaisha Rashid</p>
            <p style={signTitle}>Secretary EC</p>
            <div style={signLine}></div>
          </div>
          <div style={{ marginTop: '30px' }}>
            <p style={signName}>Daphine Nambozo</p>
            <p style={signTitle}>Commissioner</p>
            <div style={signLine}></div>
          </div>
          <div style={{ marginTop: '30px' }}>
            <p style={signName}>Odong Michael</p>
            <p style={signTitle}>Commissioner</p>
            <div style={signLine}></div>
          </div>
        </div>

         <div style={{ marginTop: '30px', fontSize: '10px', borderTop: '1px solid #000', paddingTop: '10px' }}>
              Cc: Quality assurance 
              Cc: KYUCCU patron 
              Cc:GRC CORDINATORs 
              Cc: KYUCCU president 
              Cc:out going Executive 
              Cc: all CORDINATORS
            </div>
          </div>
        )}
              

      {/* FOOTER STAMP */}
      <div style={{ textAlign: 'center', marginTop: '60px', borderTop: `1px dashed ${config.color}`, paddingTop: '20px', position: 'relative', zIndex: 1 }}>
        <p style={{ letterSpacing: '8px', fontWeight: '900', color: config.color, fontSize: '12px' }}>
          *** END OF {activeStage.toUpperCase()} REPORT ***
        </p>
        <p style={{ fontSize: '9px', color: '#aaa' }}>Verified Secure | ID: {reportFingerprint} | Mode: {activeStage.toUpperCase()}</p>
      </div>
    </div>
  </>
  );
}

// Styles
const declarationContainerStyle = {
  background: '#fff',
  border: '2px solid #000',
  padding: '30px',
  marginBottom: '40px',
  fontFamily: '"Times New Roman", Times, serif',
  position: 'relative',
  zIndex: 1,
  breakInside: 'avoid'
};

const declarationBodyStyle = {
  fontSize: '14px',
  textAlign: 'justify',
  lineHeight: '1.5',
  color: '#000'
};

const signatureGrid = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: '30px',
  marginTop: '40px'
};

const signName = { fontWeight: 'bold', margin: '0', fontSize: '13px', color: '#000' };
const signTitle = { fontSize: '11px', margin: '0', fontStyle: 'italic', color: '#333' };
const signLine = { borderTop: '1px solid #000', width: '100%', marginTop: '25px' };
const summaryHeaderStyle = { padding: '8px', border: '1px solid #3b82f6', textAlign: 'left', fontSize: '11px' };
const summaryCellStyle = { padding: '8px', border: '1px solid #ddd', fontSize: '11px' };
const tableHeaderStyle = { padding: '8px', border: '1px solid #000', textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' };
const tableCellStyle = { padding: '8px', border: '1px solid #000', fontSize: '11px' };
const posHeaderStyle = { backgroundColor: '#f2f2f2', padding: '6px', fontSize: '12px', border: '1px solid #000', margin: '0', fontWeight: 'bold' };
const sigBoxStyle = { textAlign: 'center', width: '220px' };
const voterAuditRowStyle = { borderBottom: '1px solid #eee', padding: '4px 0', fontSize: '10px', display: 'flex', alignItems: 'center', gap: '4px' };
const verifiedCheckStyle = { marginLeft: 'auto', color: '#27ae60', fontWeight: 'bold', fontSize: '10px' };
const voterGridStyle = { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', marginTop: '10px' };
const privacyLockReportStyle = { padding: '40px', border: '1px dashed #000', textAlign: 'center', marginTop: '20px' };
