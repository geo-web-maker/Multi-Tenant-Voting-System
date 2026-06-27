import React, { useEffect, useState, useMemo } from 'react';
import axios from 'axios';
import FinalReport from './FinalReport';

// 1. SHUFFLE UTILITY (Outside the component)
const shuffleArray = (array) => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

export default function Results({ apiBase }) {
  const [electionData, setElectionData] = useState({ 
    voter_turnout: 0, 
    results: [], 
    voter_roll: [] 
  });
  
  const [publicRoll, setPublicRoll] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isElectionOpen, setIsElectionOpen] = useState(true);
  const [isCertified, setIsCertified] = useState(false); 
  const [lastSynced, setLastSynced] = useState(new Date());
  const [logoUrl, setLogoUrl] = useState("");
  const [orgName, setOrgName] = useState("");
  const [universityName, setUniversityName] = useState("");
  const [universityLogoUrl, setUniversityLogoUrl] = useState("");
  const [commissionerName, setCommissionerName] = useState("");
  const [ccList, setCcList] = useState([]);
  
  const API_URL = apiBase || "https://your-railway-url.app";
  const PRIVACY_THRESHOLD = 50;
  const BATCH_SIZE = 10; 

const fetchData = async () => {
  try {
    const [resultsRes, statusRes, votersRes, brandingRes, commissionersRes] = await Promise.all([
      axios.get(`${API_URL}/election-results`),
      axios.get(`${API_URL}/election-status`),
      axios.get(`${API_URL}/admin/voters`),
      axios.get(`${API_URL}/superadmin/branding`).catch(() => ({ data: {} })),
      axios.get(`${API_URL}/superadmin/commissioners`).catch(() => ({ data: [] }))
    ]);

    const votedList = (votersRes.data || []).filter(v => v.has_voted);

    setElectionData({
      ...resultsRes.data,
      voter_roll: votedList,
      voter_turnout: resultsRes.data.voter_turnout || 0,
      results: resultsRes.data.results || []
    });

    setIsElectionOpen(statusRes.data.is_open);
    setIsCertified(statusRes.data.is_certified || false);
    setLastSynced(new Date());
    setLoading(false);

    if (brandingRes.data.logo_url)
      setLogoUrl(brandingRes.data.logo_url);
    if (brandingRes.data.org_name)
      setOrgName(brandingRes.data.org_name);
    if (brandingRes.data.university_name)
      setUniversityName(brandingRes.data.university_name);
    if (brandingRes.data.university_logo_url)
      setUniversityLogoUrl(brandingRes.data.university_logo_url);
    if (brandingRes.data.cc_list?.length)
      setCcList(brandingRes.data.cc_list);
    
    const commList = commissionersRes.data || [];
    setCommissioners(commList);
    const chief = commList.find(c => c.is_chief_commissioner);
    if (chief) setCommissionerName(chief.full_name);

  } catch (err) {
    console.error("Error fetching data:", err);
    setLoading(false);
  }
};
 
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [API_URL]);

  useEffect(() => {
    const actualCount = electionData.voter_roll.length;
    const publicCount = publicRoll.length;

    if (
      (publicCount === 0 && actualCount >= PRIVACY_THRESHOLD) || 
      (actualCount >= publicCount + BATCH_SIZE)
    ) {
      setPublicRoll(electionData.voter_roll);
    }
  }, [electionData.voter_roll, publicRoll.length]);

  const displayedVoters = useMemo(() => {
    return shuffleArray(publicRoll);
  }, [publicRoll]);

 // PASTE THIS NEW VERSION
    const handlePrint = async () => {
      setLoading(true); // Show the loading spinner while we verify status
      
      try {
        // 1. Force a fresh fetch from the backend to catch the 'is_certified' flag
        await fetchData(); 
        
        // 2. Short delay so React can swap the CSS to the "Official Blue" theme
        setTimeout(() => {
          setLoading(false);
          const originalTitle = document.title;
          const time = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }).replace(':', 'h');
          document.title = `KYU_Official_Report_${time}`;
          
          window.print();
          
          setTimeout(() => { document.title = originalTitle; }, 1000);
        }, 500); 
      } catch (err) {
        console.error("Print Sync Failed:", err);
        setLoading(false);
      }
    };

  const orderedPositions = [];
  (electionData.results || []).forEach(candidate => {
    const posName = candidate.position || "Other";
    let group = orderedPositions.find(g => g.name === posName);
    if (!group) {
      group = { name: posName, candidates: [] };
      orderedPositions.push(group);
    }
    group.candidates.push(candidate);
  });

  if (loading) return <div style={{textAlign: 'center', padding: '50px'}}>Loading Live Tally...</div>;

  return (
    <div style={{ padding: '20px', maxWidth: '700px', margin: '0 auto', fontFamily: 'system-ui, sans-serif' }}>
      
      <div className="no-print">
        <h2 style={{ textAlign: 'center', color: '#2c3e50', marginBottom: '20px' }}>📊 Election Results</h2>

        {/* 2. THE TIE ALERT (Your new addition) */}
          {!isElectionOpen && orderedPositions.some(p => {
              const max = Math.max(...p.candidates.map(c => c.votes));
              return p.candidates.filter(c => c.votes === max && max > 0).length > 1;
          }) && (
              <div style={tieWarningBanner}>
                  🚨 <strong>Contested Outcome:</strong> A tie has been detected. 
                  Official Certification is paused for affected positions.
              </div>
          )}
        
        {/* Banner reflects Certification status */}
        <div style={bannerStyle(isElectionOpen, isCertified)}>
          <div style={{ fontSize: '11px', textTransform: 'uppercase', color: '#666', fontWeight: 'bold' }}>
            {isElectionOpen ? "● Live Tallying" : (isCertified ? "✅ Official Certified Results" : "Provisional Standings")}
          </div>
          <div style={{ fontSize: '36px', fontWeight: '800', color: isCertified ? '#10b981' : '#3b82f6' }}>
            {electionData.voter_turnout}
          </div>
          <div style={{ fontSize: '13px', color: '#666' }}>Total Verified Ballots Cast</div>
        </div>

          {orderedPositions.map(position => {
              const isSolo = position.candidates.length === 1;
              const MANDATE_THRESHOLD = 100;
              
              // 1. Calculate the highest vote count in this position
              const categoryMax = Math.max(...position.candidates.map(c => c.votes || 0));
              
              // 2. Identify if multiple candidates share that top spot
              const tieCount = position.candidates.filter(c => c.votes === categoryMax && c.votes > 0).length;
              const isTie = tieCount > 1;
            
              return (
                <div key={position.name} style={{ marginBottom: '40px' }}>
                  <h3 className="position-header" style={positionHeaderStyle}>{position.name}</h3>
                  
                  {position.candidates.sort((a,b) => b.votes - a.votes).map(candidate => {
                    const percentage = electionData.voter_turnout > 0 
                      ? (candidate.votes / electionData.voter_turnout) * 100 
                      : 0;
                    
                    let winStatus = null;
                    const hasVotes = candidate.votes > 0;
                    const isTopCandidate = candidate.votes === categoryMax && hasVotes;
                    
                    if (!isElectionOpen) {
                      if (isSolo) {
                        winStatus = candidate.votes >= MANDATE_THRESHOLD ? 'MANDATE_GAINED' : 'UNDERMANDATED';
                      } else if (isTopCandidate) {
                        // If it's a tie, they aren't the winner yet
                        winStatus = isTie ? 'TIE' : 'WINNER';
                      }
                    }
            
                    return (
                      <div key={candidate.id || candidate.name} style={{ marginBottom: '20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', alignItems: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <span style={{ fontWeight: '600', color: '#1e293b' }}>{candidate.name}</span>
                            
                            {/* WINNER BADGE */}
                            {winStatus === 'WINNER' && <span style={badgeStyle('#f1c40f')}>🏆 ELECTED</span>}

                            {/* 2. NEW: Mandate Gained Badge */}
                            {winStatus === 'MANDATE_GAINED' && (
                                <span style={badgeStyle('#10b981', '#fff')}>✅ MANDATE GAINED</span>
                            )}
                            
                            {/* TIE BADGE */}
                            {winStatus === 'TIE' && <span style={badgeStyle('#e67e22', '#fff')}>⚖️ TIE (RE-RUN)</span>}
                            
                            {winStatus === 'UNDERMANDATED' && <span style={badgeStyle('#ef4444', '#fff')}>⚠️ UNDERMANDATED</span>}
                            
                            {/* LIVE STATUS */}
                            {isElectionOpen && isTopCandidate && (
                              <span style={{ color: isTie ? '#e67e22' : '#2ecc71', fontSize: '10px', fontWeight: 'bold' }}>
                                {isTie ? "● DEADLOCK" : "● LEADING"}
                              </span>
                            )}
                          </div>
                          <span style={{ fontSize: '14px', color: '#334155' }}><strong>{candidate.votes}</strong> votes</span>
                        </div>
                        
                        <div style={progressContainer}>
                           {/* Change color to Orange if it's a tie/deadlock */}
                           <div style={{
                             ...progressBar(percentage, winStatus === 'WINNER'),
                             backgroundColor: (isTie && isTopCandidate) ? '#e67e22' : 
                               (winStatus === 'MANDATE_GAINED' ? '#10b981' : 
                               (winStatus === 'WINNER' ? '#f1c40f' : '#3b82f6'))
                           }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
          })}
        
        <div style={voterRollSectionStyle}>
          <h3 style={{ fontSize: '18px', color: '#fff', marginBottom: '15px' }}>👥 Voter Participation Roll</h3>
          {electionData.voter_turnout >= PRIVACY_THRESHOLD ? (
           <div style={scrollableListStyle}>
              {displayedVoters.map((voter) => (
                <div key={voter.student_id} style={voterRowStyle}>
                  <span style={{ color: '#cbd5e1' }}>{voter.full_name}</span>
                  <span style={{ color: '#10b981', fontSize: '12px', fontWeight: 'bold' }}>
                    Verified ✓
                  </span>
                </div>
              ))} {/* This ) was the missing piece */}
              <p style={{ fontSize: '11px', color: '#64748b', textAlign: 'center', marginTop: '15px' }}>
                * Names appear in batches of {BATCH_SIZE} and are randomized to protect voter privacy.
              </p>
            </div>
          ) : (
            <div style={privacyLockStyle}>
              <p style={{ margin: '0 0 10px 0', fontSize: '18px' }}>🔒 Privacy Lock Active</p>
              <p style={{ margin: '0 0 15px 0', fontSize: '13px' }}>
                Voter names hidden until {PRIVACY_THRESHOLD} students vote.
              </p>
              <div style={thresholdBarStyle}>
                <div style={{ 
                  width: `${(electionData.voter_turnout / PRIVACY_THRESHOLD) * 100}%`, 
                  height: '100%', 
                  backgroundColor: '#3b82f6',
                  transition: 'width 1s ease-in-out'
                }} />
              </div>
              <p style={{ fontSize: '11px', marginTop: '8px' }}>
                Progress: {electionData.voter_turnout} / {PRIVACY_THRESHOLD}
              </p>
            </div>
          )}
        </div>

        <div style={{ marginTop: '40px', textAlign: 'center', borderTop: '1px solid #eee', paddingTop: '20px' }}>
          <button onClick={handlePrint} style={printBtnStyle} className="print-btn">
            🖨️ Download Official PDF Report
          </button>
          <p style={{ fontSize: '10px', color: '#94a3b8', marginTop: '10px' }}>
            Syncing live from Server... Last update: {lastSynced.toLocaleTimeString()}
          </p>
        </div>
      </div>

      <div className="print-only">
      <FinalReport 
        data={electionData} 
        totalVotes={electionData.voter_turnout} 
        isElectionOpen={isElectionOpen}
        isCertified={isCertified}
        logoUrl={logoUrl}
        orgName={orgName}
        universityName={universityName}
        universityLogoUrl={universityLogoUrl}
        commissionerName={commissionerName}
        commissioners={commissioners}
        ccList={ccList}
      />
      </div>
    </div>
  );
}

// --- UPDATED STYLES ---
// Locate your bannerStyle function at the bottom of the file
const bannerStyle = (isOpen, isCertified) => ({
  marginBottom: '30px', 
  padding: '20px', 
  borderRadius: '12px', 
  textAlign: 'center',
  // Background logic
  background: isOpen ? '#f0fdf4' : (isCertified ? '#ecfdf5' : '#fff7ed'), 
  // Border logic
  borderBottom: `4px solid ${isOpen ? '#2ecc71' : (isCertified ? '#10b981' : '#f39c12')}`,
  boxShadow: '0 4px 6px -1px rgba(0,0,0,0.05)'
});

const badgeStyle = (bgColor, textColor = '#000') => ({
  backgroundColor: bgColor, 
  color: textColor, 
  fontSize: '10px', 
  padding: '3px 10px', 
  borderRadius: '20px', 
  fontWeight: '800'
});

const positionHeaderStyle = {
  backgroundColor: '#f8fafc', color: '#3b82f6', padding: '8px 15px', borderRadius: '8px',
  fontSize: '18px', fontWeight: 'bold', borderLeft: '4px solid #3b82f6', marginBottom: '20px'
};

const progressContainer = { width: '100%', backgroundColor: '#f1f5f9', borderRadius: '20px', height: '10px', overflow: 'hidden' };
const progressBar = (pct, isWinner) => ({ 
  width: `${pct}%`, height: '100%', backgroundColor: isWinner ? '#f1c40f' : '#3b82f6', transition: 'width 1.5s ease-in-out' 
});

const tieWarningBanner = {
  backgroundColor: '#fff7ed',
  border: '1px solid #fb923c',
  color: '#9a3412',
  padding: '12px',
  borderRadius: '8px',
  marginBottom: '20px',
  textAlign: 'center',
  fontSize: '13px',
  fontWeight: '600'
};

const voterRollSectionStyle = { marginTop: '40px', padding: '25px', backgroundColor: '#0f172a', borderRadius: '15px', border: '1px solid #1e293b' };
const scrollableListStyle = { maxHeight: '300px', overflowY: 'auto', paddingRight: '10px' };
const voterRowStyle = { display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #1e293b' };
const privacyLockStyle = { padding: '20px', textAlign: 'center', color: '#94a3b8' };
const thresholdBarStyle = { width: '100%', height: '8px', background: '#334155', borderRadius: '4px', overflow: 'hidden' };

const printBtnStyle = {
  padding: '12px 24px', backgroundColor: '#1e293b', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600'
};
