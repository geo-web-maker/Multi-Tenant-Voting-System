import React, { useEffect, useState, useMemo, useRef } from 'react';
import api from '../api';
import FinalReport from './FinalReport';
import { Icon } from './icons.jsx';

// 1. SHUFFLE UTILITY (Outside the component)
const shuffleArray = (array) => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

export default function Results() {
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
  // commissionerName / commissioners / ccList are deliberately NOT held here
  // any more. The declaration, signature grid and distribution list are
  // institutional/legal content and now live only behind the authenticated
  // /admin/official-report endpoint. Hiding them with a client-side
  // `isCertified &&` was never a boundary — the code shipped in the public
  // bundle either way.
  const [rollUnlocked, setRollUnlocked] = useState(false);
  
const PRIVACY_THRESHOLD = 50;
  const BATCH_SIZE = 10; 

// Results + status refresh every 5s. The voter roll (heavier, rate-limited, changes slowly) refreshes
// every ROLL_EVERY ticks, and branding is loaded once — polling all four every 5s was what got the
// roll rate-limited.
const ROLL_EVERY = 6;                 // 6 ticks x 5s = 30s
const tickRef = useRef(0);
const brandingLoadedRef = useRef(false);

const fetchData = async ({ force = false } = {}) => {
  const tick = tickRef.current++;
  const wantRoll = force || tick % ROLL_EVERY === 0;
  const wantBranding = !brandingLoadedRef.current;
  try {
    // A failed roll/branding request resolves to null and the previous value is KEPT. Falling back to
    // "locked, empty roll" on any error (e.g. a 429) made the page claim the privacy lock was active
    // when 1820 people had voted.
    const [resultsRes, statusRes, votersRes, brandingRes] = await Promise.all([
      api.get('/election-results'),
      api.get('/election-status'),
      wantRoll ? api.get('/election-results/voter-roll').catch(() => null) : Promise.resolve(null),
      wantBranding ? api.get('/superadmin/branding').catch(() => null) : Promise.resolve(null),
    ]);

    // The privacy threshold is enforced server-side — below it the backend returns an empty roll, so
    // the names are not merely hidden in the UI, they are never sent.
    let newRoll = null;   // null = keep whatever roll we already have
    if (votersRes) {
      const rollPayload = votersRes.data || {};
      setRollUnlocked(Boolean(rollPayload.unlocked));
      newRoll = Array.isArray(rollPayload) ? rollPayload : (rollPayload.roll || []);
    }

    setElectionData(prev => ({
      ...resultsRes.data,
      voter_roll: newRoll ?? prev.voter_roll,
      voter_turnout: resultsRes.data.voter_turnout || 0,
      results: resultsRes.data.results || []
    }));

    setIsElectionOpen(statusRes.data.is_open);
    setIsCertified(statusRes.data.is_certified || false);
    setLastSynced(new Date());
    setLoading(false);

    if (brandingRes) {
      brandingLoadedRef.current = true;
      const b = brandingRes.data || {};
      if (b.logo_url) setLogoUrl(b.logo_url);
      if (b.org_name) setOrgName(b.org_name);
      if (b.university_name) setUniversityName(b.university_name);
      if (b.university_logo_url) setUniversityLogoUrl(b.university_logo_url);
    }
  } catch (err) {
    console.error("Error fetching data:", err);
    setLoading(false);
  }
};
 
  useEffect(() => {
    // Initial load + polling; fetchData sets state as the response arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const actualCount = electionData.voter_roll.length;
    const publicCount = publicRoll.length;

    if (
      (publicCount === 0 && actualCount >= PRIVACY_THRESHOLD) || 
      (actualCount >= publicCount + BATCH_SIZE)
    ) {
      // Reveal the roll in batches as new data arrives.
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
        await fetchData({ force: true }); 
        
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
    <div style={{ padding: 'clamp(12px, 4vw, 20px)', maxWidth: '700px', margin: '0 auto', width: '100%', boxSizing: 'border-box', fontFamily: 'system-ui, sans-serif' }}>
      
      <div className="no-print">
        <h2 style={{ textAlign: 'center', color: '#2c3e50', marginBottom: '20px' }}><Icon name="chart" /> Election Results</h2>

        {/* 2. THE TIE ALERT (Your new addition) */}
          {!isElectionOpen && orderedPositions.some(p => {
              const max = Math.max(...p.candidates.map(c => c.votes));
              return p.candidates.filter(c => c.votes === max && max > 0).length > 1;
          }) && (
              <div style={tieWarningBanner}>
                  <Icon name="alarm" /> <strong>Contested Outcome:</strong> A tie has been detected. 
                  Official Certification is paused for affected positions.
              </div>
          )}
        
        {/* Banner reflects Certification status */}
        <div style={bannerStyle(isElectionOpen, isCertified)}>
          <div style={{ fontSize: '11px', textTransform: 'uppercase', color: '#666', fontWeight: 'bold' }}>
            {isElectionOpen ? <><Icon name="dot" /> Live Tallying</> : (isCertified ? <><Icon name="success" /> Official Certified Results</> : "Provisional Standings")}
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
                            {winStatus === 'WINNER' && <span style={badgeStyle('var(--warning)')}><Icon name="trophy" /> ELECTED</span>}

                            {/* 2. NEW: Mandate Gained Badge */}
                            {winStatus === 'MANDATE_GAINED' && (
                                <span style={badgeStyle('#10b981', '#fff')}><Icon name="success" /> MANDATE GAINED</span>
                            )}
                            
                            {/* TIE BADGE */}
                            {winStatus === 'TIE' && <span style={badgeStyle('#e67e22', '#fff')}><Icon name="scale" /> TIE (RE-RUN)</span>}
                            
                            {winStatus === 'UNDERMANDATED' && <span style={badgeStyle('#ef4444', '#fff')}><Icon name="warning" /> UNDERMANDATED</span>}
                            
                            {/* LIVE STATUS */}
                            {isElectionOpen && isTopCandidate && (
                              <span style={{ color: isTie ? '#e67e22' : 'var(--success)', fontSize: '10px', fontWeight: 'bold' }}>
                                {isTie ? <><Icon name="dot" /> DEADLOCK</> : <><Icon name="dot" /> LEADING</>}
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
                               (winStatus === 'WINNER' ? 'var(--warning)' : '#3b82f6'))
                           }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
          })}
        
        <div style={voterRollSectionStyle}>
          <h3 style={{ fontSize: '18px', color: 'var(--text-color)', marginBottom: '15px' }}><Icon name="users" /> Voter Participation Roll</h3>
          {rollUnlocked && displayedVoters.length > 0 ? (
           <div style={scrollableListStyle}>
              {displayedVoters.map((voter, idx) => (
                <div key={`${voter.full_name}-${idx}`} style={voterRowStyle}>
                  <span style={{ color: 'var(--text-color)' }}>{voter.full_name}</span>
                  <span style={{ color: 'var(--success)', fontSize: '12px', fontWeight: 'bold' }}>
                    Verified <Icon name="check" />
                  </span>
                </div>
              ))} {/* This ) was the missing piece */}
              <p style={{ fontSize: '11px', color: '#64748b', textAlign: 'center', marginTop: '15px' }}>
                * Names appear in batches of {BATCH_SIZE} and are randomized to protect voter privacy.
              </p>
            </div>
          ) : electionData.voter_turnout >= PRIVACY_THRESHOLD ? (
            // Threshold is met, so the lock is NOT active — the roll just hasn't (re)loaded yet, e.g. a
            // rate-limited or failed request. Never claim a privacy lock the numbers contradict.
            <div style={privacyLockStyle}>
              <p style={{ margin: 0, fontSize: '13px' }}>Loading the participation roll…</p>
            </div>
          ) : (
            <div style={privacyLockStyle}>
              <p style={{ margin: '0 0 10px 0', fontSize: '18px' }}><Icon name="lock" /> Privacy Lock Active</p>
              <p style={{ margin: '0 0 15px 0', fontSize: '13px' }}>
                Voter names hidden until {PRIVACY_THRESHOLD} students vote.
              </p>
              <div style={thresholdBarStyle}>
                <div style={{ 
                  width: `${Math.min(100, (electionData.voter_turnout / PRIVACY_THRESHOLD) * 100)}%`, 
                  height: '100%', 
                  backgroundColor: 'var(--info)',
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
            <Icon name="print" /> Download Public Results Report
          </button>
          <p style={{ fontSize: '10px', color: '#94a3b8', marginTop: '10px' }}>
            Syncing live from Server... Last update: {lastSynced.toLocaleTimeString()}
          </p>
          <p style={{ fontSize: '10px', color: '#94a3b8', marginTop: '4px', maxWidth: '520px', margin: '4px auto 0' }}>
            This is the public record: tallies, turnout, the per-position breakdown,
            certification status and the participation roll. The signed declaration and
            signature page are issued separately by the Electoral Commission.
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
  borderBottom: `4px solid ${isOpen ? 'var(--success)' : (isCertified ? '#10b981' : '#f39c12')}`,
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
  width: `${pct}%`, height: '100%', backgroundColor: isWinner ? 'var(--warning)' : '#3b82f6', transition: 'width 1.5s ease-in-out' 
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

const voterRollSectionStyle = { marginTop: '40px', padding: '25px', backgroundColor: 'var(--card-bg)', borderRadius: '15px', border: '1px solid var(--border-color)' };
const scrollableListStyle = { maxHeight: '300px', overflowY: 'auto', paddingRight: '10px' };
const voterRowStyle = { display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-color)' };
const privacyLockStyle = { padding: '20px', textAlign: 'center', color: 'var(--text-muted)' };
const thresholdBarStyle = { width: '100%', height: '8px', background: 'var(--border-color)', borderRadius: '4px', overflow: 'hidden' };
const printBtnStyle = {
  padding: '12px 24px', backgroundColor: '#1e293b', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600'
};
