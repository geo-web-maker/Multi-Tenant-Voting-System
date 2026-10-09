import React, { useEffect, useState, useMemo, useRef } from 'react';
import api from '../api';
import usePolling from '../hooks/usePolling';
import FinalReport from './FinalReport';
import { Icon } from './icons.jsx';
import { PublicTurnoutBreakdown } from './TurnoutBreakdown';
import { LoadingBlock } from './Spinner.jsx';
import { resultsState, notStartedMessage } from '../resultsState';
import { fmtZoned, DEFAULT_TZ } from '../tz';
import { getTemplate } from '../template';

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
    voter_roll: [],
    results_released: true   // avoids a placeholder flash before the first response arrives
  });
  
  const [publicRoll, setPublicRoll] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isElectionOpen, setIsElectionOpen] = useState(true);
  const [isCertified, setIsCertified] = useState(false); 
  const [statusInfo, setStatusInfo] = useState({});   // /election-status payload, for resultsState()
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
  const [rollQuery, setRollQuery] = useState("");
  const ROLL_SEARCH_MIN_CHARS = 3;
  const ROLL_SEARCH_MAX_RESULTS = 20;
  
const PRIVACY_THRESHOLD = 50;
  const BATCH_SIZE = 10; 

// Results + status refresh on a cadence set by the election state (see usePolling below). The voter roll
// (heavier, rate-limited, changes slowly) refreshes every ROLL_EVERY ticks, and branding is loaded once —
// polling all four on every tick was what got the roll rate-limited.
const ROLL_EVERY = 3;                 // 3 ticks x 10s = 30s while voting is open
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
      results: resultsRes.data.results || [],
      results_released: resultsRes.data.results_released !== false
    }));

    setIsElectionOpen(statusRes.data.is_open);
    setIsCertified(statusRes.data.is_certified || false);
    setStatusInfo(statusRes.data || {});
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
  }, []);

  // 10 s while voting is open, 60 s otherwise, and stop once the result is certified (it can no longer
  // change). Unlike the old setInterval this pauses in a background tab and never overlaps requests.
  usePolling(() => fetchData(), isElectionOpen ? 10000 : 60000, !isCertified, { minGapMs: 5000 });

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

  // Client-side only: filters names already revealed in publicRoll. Never
  // queries the backend, so a search can't surface anyone the batched reveal
  // hasn't already shown. Requires 3+ chars so it can't be used to dump the
  // whole roll, and caps results so it can't be used to scrape it either.
  const trimmedRollQuery = rollQuery.trim();
  const isSearchingRoll = trimmedRollQuery.length >= ROLL_SEARCH_MIN_CHARS;
  const rollSearchResults = useMemo(() => {
    if (!isSearchingRoll) return [];
    const q = trimmedRollQuery.toLowerCase();
    return publicRoll
      .filter(v => v.full_name?.toLowerCase().includes(q))
      .slice(0, ROLL_SEARCH_MAX_RESULTS);
  }, [isSearchingRoll, trimmedRollQuery, publicRoll]);

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

  const pageState = resultsState({ ...statusInfo, is_open: isElectionOpen }, electionData);
  const notStarted = pageState === 'not_started';
  const noVotes = pageState === 'no_votes';

  // Template seam: `bp` is null in the standard UI; every branch falls through to the original markup.
  const bp = getTemplate();
  const badge = (tone, bg, fg, icon, label) => (bp
    ? <bp.Pill tone={tone}><Icon name={icon} /> {label}</bp.Pill>
    : <span className="cand-badge" style={badgeStyle(bg, fg)}><Icon name={icon} /> {label}</span>);

  if (loading) return <div style={{textAlign: 'center', padding: '50px'}}><LoadingBlock text="Loading Live Tally…" /></div>;

  return (
    <div style={{ padding: 'clamp(12px, 4vw, 20px)', maxWidth: '700px', margin: '0 auto', width: '100%', boxSizing: 'border-box', fontFamily: 'system-ui, sans-serif' }}>
      
      <div className="no-print">
        <h2 style={{ textAlign: 'center', color: 'var(--bp-tx, #2c3e50)', marginBottom: '20px' }}>Election Results</h2>

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
        
        {notStarted && (
          <div style={{ textAlign: 'center', padding: '30px 20px', color: 'var(--bp-mu, #475569)', border: '1px dashed var(--bp-line-ui, #ccc)', borderRadius: '10px', marginBottom: '20px' }}>
            <Icon name="alarm" />
            <div style={{ marginTop: '8px', fontWeight: 600 }}>
              {notStartedMessage(statusInfo.voting_opens_at ? fmtZoned(statusInfo.voting_opens_at, DEFAULT_TZ) : '')}
            </div>
          </div>
        )}

        {/* Banner reflects Certification status */}
        {!notStarted && (bp ? (
          <bp.Stat
            tone={isElectionOpen || isCertified ? 'ok' : 'warn'}
            pill={isElectionOpen ? <><Icon name="dot" /> Live Tallying</> : (isCertified ? <><Icon name="success" /> Official Certified Results</> : "Provisional Standings")}
            value={electionData.voter_turnout}
            note="Total Verified Ballots Cast"
          />
        ) : (
        <div style={bannerStyle(isElectionOpen, isCertified)}>
          <div style={{ fontSize: '11px', textTransform: 'uppercase', color: '#666', fontWeight: 'bold' }}>
            {isElectionOpen ? <><Icon name="dot" /> Live Tallying</> : (isCertified ? <><Icon name="success" /> Official Certified Results</> : "Provisional Standings")}
          </div>
          <div style={{ fontSize: '36px', fontWeight: '800', color: isCertified ? 'var(--bp-ok, #10b981)' : 'var(--bp-ac, #3b82f6)' }}>
            {electionData.voter_turnout}
          </div>
          <div style={{ fontSize: '13px', color: '#666' }}>Total Verified Ballots Cast</div>
        </div>
        ))}

        {noVotes && (
          <div style={{ textAlign: 'center', padding: '20px', color: 'var(--bp-mu, #666)', marginBottom: '20px' }}>No votes yet.</div>
        )}

        {notStarted || noVotes ? null : !electionData.results_released ? (
          <div style={{ textAlign: 'center', padding: '30px 20px', color: 'var(--bp-mu, #666)', border: '1px dashed var(--bp-line-ui, #ccc)', borderRadius: '10px', marginBottom: '20px' }}>
            <Icon name="lock" />
            <div style={{ marginTop: '8px', fontWeight: 600 }}>Candidate results not yet published</div>
            <div style={{ fontSize: '13px', marginTop: '4px' }}>
              Turnout above updates live. The per-candidate breakdown is released once
              {isElectionOpen ? " voting closes and results are certified." : " results are certified."}
            </div>
          </div>
        ) : (
          orderedPositions.map(position => {
              const isSolo = position.candidates.length === 1;
              const MANDATE_THRESHOLD = 100;
              
              // 1. Calculate the highest vote count in this position
              const categoryMax = Math.max(...position.candidates.map(c => c.votes || 0));
              
              // 2. Identify if multiple candidates share that top spot
              const tieCount = position.candidates.filter(c => c.votes === categoryMax && c.votes > 0).length;
              const isTie = tieCount > 1;

              // Bars show each candidate's share of THIS position's votes (same basis as the
              // printed report's Share column). Dividing by overall turnout was wrong: the
              // numbers can exceed 100% and every bar pinned at full width.
              const positionTotal = position.candidates.reduce((sum, c) => sum + (c.votes || 0), 0);
            
              return (
                <div key={position.name} style={{ marginBottom: '40px' }}>
                  {bp ? <bp.PositionHeading>{position.name}</bp.PositionHeading> : (
                  <h3 className="position-header" style={positionHeaderStyle}>{position.name}</h3>
                  )}
                  
                  {position.candidates.sort((a,b) => b.votes - a.votes).map(candidate => {
                    const percentage = positionTotal > 0
                      ? (candidate.votes / positionTotal) * 100
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
            
                    const Row = bp ? bp.Meter : 'div';
                    const rowProps = bp ? { pct: percentage, accent: isTopCandidate } : { className: 'cand-row' };
                    return (
                      <Row key={candidate.id || candidate.name} {...rowProps}>
                        {/* Line 1: name (wraps freely) + votes (never squeezed) */}
                        <div className="cand-top">
                          <span className="cand-name">{candidate.name}</span>
                          <span className="cand-votes"><strong>{candidate.votes}</strong> votes <span className="cand-pct">({percentage.toFixed(1)}%)</span></span>
                        </div>

                        {/* Line 2: status badge gets its own row, so it can never
                            crush the name or the vote count. Rendered only when
                            there is a status to show. */}
                        {(winStatus || (isElectionOpen && isTopCandidate)) && (
                          <div className="cand-badges">
                            {winStatus === 'WINNER' && badge('ok', 'var(--warning)', 'var(--bp-ai, #1e293b)', 'trophy', 'ELECTED')}
                            {winStatus === 'MANDATE_GAINED' && badge('ok', 'var(--bp-ok, #10b981)', 'var(--bp-ai, #fff)', 'success', 'MANDATE GAINED')}
                            {winStatus === 'TIE' && badge('warn', 'var(--bp-wn, #e67e22)', 'var(--bp-ai, #fff)', 'scale', 'TIE (RE-RUN)')}
                            {winStatus === 'UNDERMANDATED' && badge('neg', 'var(--bp-no, #ef4444)', 'var(--bp-ai, #fff)', 'warning', 'UNDERMANDATED')}
                            {isElectionOpen && isTopCandidate && (bp ? (
                              <bp.Pill tone={isTie ? 'warn' : 'ok'}>
                                {isTie ? <><Icon name="dot" /> DEADLOCK</> : <><Icon name="dot" /> LEADING</>}
                              </bp.Pill>
                            ) : (
                              <span className="cand-live" style={{ color: isTie ? 'var(--bp-wn, #e67e22)' : 'var(--success)' }}>
                                {isTie ? <><Icon name="dot" /> DEADLOCK</> : <><Icon name="dot" /> LEADING</>}
                              </span>
                            ))}
                          </div>
                        )}

                        {!bp && (
                        <div style={progressContainer}>
                           {/* Change color to Orange if it's a tie/deadlock */}
                           <div style={{
                             ...progressBar(percentage, winStatus === 'WINNER'),
                             backgroundColor: (isTie && isTopCandidate) ? 'var(--bp-wn, #e67e22)' : 
                               (winStatus === 'MANDATE_GAINED' ? 'var(--bp-ok, #10b981)' : 
                               (winStatus === 'WINNER' ? 'var(--warning)' : 'var(--bp-ac, #3b82f6)'))
                           }} />
                        </div>
                        )}
                      </Row>
                    );
                  })}
                </div>
              );
          })
        )}
        
        {!notStarted && !noVotes && (
        <div style={voterRollSectionStyle}>
          <h3 style={{ fontSize: '18px', color: 'var(--text-color)', marginBottom: '15px' }}>Voter Participation Roll</h3>
          {rollUnlocked && displayedVoters.length > 0 ? (
           <div style={scrollableListStyle}>
              <input
                type="text"
                value={rollQuery}
                onChange={(e) => setRollQuery(e.target.value)}
                placeholder="Search your name (3+ letters)…"
                aria-label="Search the voter participation roll"
                className="roll-search-input"
                style={rollSearchInputStyle}
              />
              {isSearchingRoll ? (
                rollSearchResults.length > 0 ? (
                  rollSearchResults.map((voter, idx) => (
                    <div key={`${voter.full_name}-${idx}`} style={voterRowStyle}>
                      <span style={{ color: 'var(--text-color)' }}>{voter.full_name}</span>
                      <span style={{ color: 'var(--success)', fontSize: '12px', fontWeight: 'bold' }}>
                        Verified <Icon name="check" />
                      </span>
                    </div>
                  ))
                ) : (
                  <p style={{ fontSize: '12px', color: 'var(--bp-mu, #64748b)', margin: '10px 0' }}>
                    No match in the published list. Names appear in batches, so a recent voter may not show yet.
                  </p>
                )
              ) : (
                displayedVoters.map((voter, idx) => (
                  <div key={`${voter.full_name}-${idx}`} style={voterRowStyle}>
                    <span style={{ color: 'var(--text-color)' }}>{voter.full_name}</span>
                    <span style={{ color: 'var(--success)', fontSize: '12px', fontWeight: 'bold' }}>
                      Verified <Icon name="check" />
                    </span>
                  </div>
                ))
              )}
              <p style={{ fontSize: '11px', color: 'var(--bp-mu, #64748b)', textAlign: 'center', marginTop: '15px' }}>
                * Names appear in batches of {BATCH_SIZE} and are randomized to protect voter privacy.
              </p>
            </div>
          ) : electionData.voter_turnout >= PRIVACY_THRESHOLD ? (
            // Threshold is met, so the lock is NOT active — the roll just hasn't (re)loaded yet, e.g. a
            // rate-limited or failed request. Never claim a privacy lock the numbers contradict.
            <div style={privacyLockStyle}>
              <LoadingBlock text="Loading the participation roll…" />
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
        )}

        {!notStarted && !noVotes && <PublicTurnoutBreakdown />}

        <div style={{ marginTop: '40px', textAlign: 'center', borderTop: '1px solid #eee', paddingTop: '20px' }}>
          {!notStarted && (
          <button onClick={handlePrint} style={printBtnStyle} className="print-btn">
            Download Public Results Report
          </button>
          )}
          <p style={{ fontSize: '10px', color: 'var(--bp-mu, #94a3b8)', marginTop: '10px' }}>
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
        resultsReleased={electionData.results_released}
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
  borderBottom: `4px solid ${isOpen ? 'var(--success)' : (isCertified ? 'var(--bp-ok, #10b981)' : 'var(--bp-wn, #f39c12)')}`,
  boxShadow: '0 4px 6px -1px rgba(0,0,0,0.05)'
});

const badgeStyle = (bgColor, textColor = '#000') => ({
  backgroundColor: bgColor,
  color: textColor,
  fontSize: '10px',
  padding: '3px 10px',
  borderRadius: '20px',
  fontWeight: '800',
  display: 'inline-flex',
  alignItems: 'center',
  gap: '4px',
  whiteSpace: 'nowrap',
});

const positionHeaderStyle = {
  backgroundColor: '#f8fafc', color: 'var(--bp-ac, #3b82f6)', padding: '8px 15px', borderRadius: '8px',
  fontSize: '18px', fontWeight: 'bold', borderLeft: '4px solid var(--bp-ac, #3b82f6)', marginBottom: '20px'
};

const progressContainer = { width: '100%', backgroundColor: 'var(--surface-2)', borderRadius: '20px', height: '10px', overflow: 'hidden' };
const progressBar = (pct, isWinner) => ({ 
  width: `${pct}%`, height: '100%', backgroundColor: isWinner ? 'var(--warning)' : 'var(--bp-ac, #3b82f6)', transition: 'width 1.5s ease-in-out' 
});

const tieWarningBanner = {
  backgroundColor: 'var(--bp-wn-tint, #fff7ed)',
  border: '1px solid var(--bp-wn-edge, #fb923c)',
  color: 'var(--bp-tx, #9a3412)',
  padding: '12px',
  borderRadius: '8px',
  marginBottom: '20px',
  textAlign: 'center',
  fontSize: '13px',
  fontWeight: '600'
};

const voterRollSectionStyle = { marginTop: '40px', padding: '25px', backgroundColor: 'var(--card-bg)', borderRadius: '15px', border: '1px solid var(--border-color)' };
const scrollableListStyle = { maxHeight: '300px', overflowY: 'auto', paddingRight: '10px' };
const rollSearchInputStyle = { width: '100%', boxSizing: 'border-box', padding: '10px 12px', marginBottom: '12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px' };
const voterRowStyle = { display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-color)' };
const privacyLockStyle = { padding: '20px', textAlign: 'center', color: 'var(--text-muted)' };
const thresholdBarStyle = { width: '100%', height: '8px', background: 'var(--border-color)', borderRadius: '4px', overflow: 'hidden' };
const printBtnStyle = {
  padding: '12px 24px', backgroundColor: 'var(--bp-ac, #1e293b)', color: 'var(--bp-ai, #fff)', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600'
};
