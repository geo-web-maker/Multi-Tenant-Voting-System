import React, { useEffect, useState } from 'react';
import api from '../api';

export default function BallotBox({ studentId, onVoteSuccess, propCandidates, isPreview = false, orgName = "" }) {
  const [candidates, setCandidates] = useState(propCandidates || []);
  const [loading, setLoading] = useState(!propCandidates); // Don't show loading if we already have data
  const [isVoting, setIsVoting] = useState(false);
  const [ballot, setBallot] = useState({});
  const [showSummary, setShowSummary] = useState(false);
  // Add this near your other state declarations
  const [statusModal, setStatusModal] = useState({ 
    show: false, 
    title: '', 
    message: '', 
    type: 'success' 
  });
  
  // NEW: State for the Clear All Confirmation Modal
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [countdown, setCountdown] = useState(0);

  // FIXED: Single declaration of handleSelect with Toggle Logic
  const handleSelect = (position, candidateId) => {
    setBallot(prev => {
      const newBallot = { ...prev };
      if (newBallot[position] === candidateId) {
        delete newBallot[position]; 
      } else {
        newBallot[position] = candidateId;
      }
      return newBallot;
    });
  };

  const confirmClearAll = () => {
    setBallot({});
    setShowClearConfirm(false);
  };

    useEffect(() => {
      // If data was passed from App.jsx, use it and stop loading immediately
      if (propCandidates && propCandidates.length > 0) {
        setCandidates(propCandidates);
        setLoading(false);
        return;
      }
    
      // Otherwise (like when a voter logs in), fetch it from the API
      const fetchCandidates = async () => {
        try {
          const res = await api.get(`/candidates`);
          setCandidates(res.data);
        } catch (err) { 
          console.error(err); 
        } finally { 
          setLoading(false); 
        }
      };
      fetchCandidates();
    }, [propCandidates]);

  useEffect(() => {
    let timer;
    if (showSummary && countdown > 0) {
      timer = setInterval(() => {
        setCountdown((prev) => prev - 1);
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [showSummary, countdown]);

  const openSummary = () => {
    setCountdown(3);
    setShowSummary(true);
  };

  const submitFinalBallot = async () => {
    const selectedIds = Object.values(ballot);
    setIsVoting(true);
    try {
      const res = await api.post(`/vote-bulk`, {
        student_id: studentId,
        candidate_ids: selectedIds
      });
      
      if (res.data.status === "success") {
        // SKIP THE MODAL: Go straight to the success screen
        onVoteSuccess(); 
      }
    } catch (err) {
      setIsVoting(false);
      setShowSummary(false);
      // Keep the Error Modal so they know why it failed
      setStatusModal({
        show: true,
        title: "Submission Error",
        message: err.response?.data?.detail || "Connection failed.",
        type: "error"
      });
    }
  };

  if (loading) return <div style={{ textAlign: 'center', color: '#fff' }}>Loading...</div>;

  const groupedCandidates = candidates.reduce((groups, c) => {
    const pos = c.position || "Other";
    if (!groups[pos]) groups[pos] = [];
    groups[pos].push(c);
    return groups;
  }, {});

  const getCandidateName = (id) => candidates.find(c => (c._id || c.id) === id)?.name || "Unknown";

  return (
    <div style={{ textAlign: 'center', color: '#fff', paddingBottom: '120px' }}>
      {isPreview && (
      <div style={{ 
        backgroundColor: '#fee2e2', 
        color: '#b91c1c', 
        padding: '15px', 
        borderRadius: '12px', 
        margin: '10px 10px 25px 10px', 
        fontWeight: '800',
        border: '1px solid #fecaca' 
      }}>
        ⚠️ SAMPLE BALLOT GUIDE — VOTING DISABLED
      </div>
    )}
      <h1 style={{ color: '#3b82f6', fontSize: '24px' }}>{orgName ? `${orgName} ELECTION`.toUpperCase() : "ELECTION"}</h1>
      
      {Object.keys(groupedCandidates).map((pos) => (
        <div key={pos} style={{ marginBottom: '30px', padding: '0 10px' }}>
          {/* The Header (Fixes the visibility of position names) */}
          <h3 
            className="position-header" 
            style={{ 
              color: '#1e293b',             // Dark text for contrast on gold
              backgroundColor: 'var(--warning)',
              padding: '12px 20px', 
              borderRadius: '10px', 
              textAlign: 'left', 
              marginBottom: '20px', 
              borderLeft: 'var(--brand-primary, #2c3e50)', // Darker left accent
              fontSize: '14px', 
              fontWeight: '800', 
              textTransform: 'uppercase',
              letterSpacing: '1px'
            }}
          >
            {pos}
          </h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {groupedCandidates[pos].map(c => {
              const isSelected = ballot[pos] === (c._id || c.id);
              return (
                <div 
                  key={c._id || c.id} 
                  onClick={() => handleSelect(pos, c._id || c.id)}
                  style={{ 
                    ...horizontalCardStyle, 
                    border: isSelected ? '2px solid #3b82f6' : '1px solid #334155',
                    backgroundColor: isSelected ? 'rgba(59, 130, 246, 0.15)' : '#1e293b'
                  }}
                >
                  {/* 1. Image and Name (Grouped together on the left) */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                    <img src={c.image_url} alt="" style={horizontalImageStyle} />
                    <h4 style={{ color: '#fff', margin: 0, fontSize: '16px', fontWeight: '600' }}>
                      {c.name}
                    </h4>
                  </div>
      
                  {/* 2. The Tick Box (Pushed to the far right) */}
                  <div style={{ 
                    ...tickBoxStyle, 
                    backgroundColor: isSelected ? '#3b82f6' : 'transparent',
                    borderColor: isSelected ? '#3b82f6' : '#64748b'
                  }}>
                    {isSelected && <span style={{ color: '#fff', fontSize: '14px', fontWeight: 'bold' }}>✔</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* FOOTER BAR */}
      {!isPreview && (
      <div style={footerBarStyle}>
        <div style={{ display: 'flex', gap: '15px', justifyContent: 'center', maxWidth: '600px', margin: '0 auto' }}>
          <button 
            onClick={() => setShowClearConfirm(true)} 
            style={clearAllBtnStyle}
            disabled={Object.keys(ballot).length === 0}
          >
            🗑️ Clear All
          </button>
      
          <button 
            onClick={openSummary} 
            style={{...submitBallotBtnStyle, flex: 2, opacity: Object.keys(ballot).length === 0 ? 0.5 : 1}} 
            disabled={Object.keys(ballot).length === 0}
          >
            REVIEW & SUBMIT ({Object.keys(ballot).length})
          </button>
        </div>
      </div>
      )}

      {/* CLEAR ALL CONFIRMATION MODAL */}
      {!isPreview && showClearConfirm && (
        <div style={modalOverlayStyle}>
          <div className="modal-content" style={{...modalContentStyle, textAlign: 'center'}}>
           {/* Icon for visual emphasis */}
            <div style={{ fontSize: '40px', marginBottom: '10px' }}>🗑️</div>
            
            <h2 style={{ color: '#e11d48', marginTop: 0, fontWeight: '800' }}>
              Reset Entire Ballot?
            </h2>
            <p style={{ color: 'var(--text-muted)' }}>This will clear all your currently selected candidates. This action cannot be undone.</p>
            <div style={{ display: 'flex', gap: '15px', marginTop: '20px' }}>
              <button onClick={() => setShowClearConfirm(false)} style={cancelBtnStyle}>Keep My Votes</button>
              <button onClick={confirmClearAll} style={{...confirmBtnStyle, backgroundColor: '#e11d48'}}>Yes, Clear All</button>
            </div>
          </div>
        </div>
      )}

      {/* SUMMARY MODAL */}
      {!isPreview && showSummary && (
        <div style={modalOverlayStyle}>
          <div className="modal-content" style={modalContentStyle}>
            <h2 style={{marginTop: 0 }}>Review Your Ballot</h2>
            <p style={{fontSize: '14px', marginBottom: '10px' }}>Verify your selections. Once submitted, you cannot change your vote.</p>
            
            <div style={summaryListStyle}>
             {Object.keys(groupedCandidates).map((pos) => {
                const selectedId = ballot[pos];
                // Find the full candidate object from the master list using the ID
                const selectedCandidate = candidates.find(c => (c._id || c.id) === selectedId);
              
                return (
                  <div key={pos} style={summaryRowStyle}>
                    {/* Position Name on the Left */}
                    <strong style={{ color: '#2563eb', fontSize: '13px', flex: '1' }}>
                      {pos}:
                    </strong>
                    
                    {/* Candidate Name and Photo on the Right */}
                    <div style={{ 
                      flex: '1.5', 
                      display: 'flex', 
                      alignItems: 'center', 
                      justifyContent: 'flex-end', 
                      gap: '10px' 
                    }}>
                      {selectedCandidate ? (
                        <>
                          <span style={{ color: 'var(--text-color)', fontWeight: '700', fontSize: '13px', textAlign: 'right' }}>
                            {selectedCandidate.name}
                          </span>
                          <img 
                            src={selectedCandidate.image_url} 
                            alt="" 
                            style={{ 
                              width: '35px', 
                              height: '35px', 
                              borderRadius: '50%', 
                              objectFit: 'cover', 
                              border: '1px solid var(--border-color)',
                              backgroundColor: 'var(--surface-2)'
                            }} 
                          />
                        </>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '13px' }}>
                          Abstain
                        </span>
                      )}
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ display: 'flex', gap: '15px', marginTop: '20px' }}>
              <button onClick={() => setShowSummary(false)} style={cancelBtnStyle}>Change Selections</button>
              <button 
                onClick={submitFinalBallot} 
                disabled={isVoting || countdown > 0} 
                style={{
                    ...confirmBtnStyle, 
                    backgroundColor: (isVoting || countdown > 0) ? '#94a3b8' : '#10b981'
                }}
              >
                {isVoting ? "Casting..." : countdown > 0 ? `Wait (${countdown}s)` : "Confirm & Cast Vote"}
              </button>
            </div>
          </div>
        </div>
      )}

     {/* ONLY SHOW MODAL FOR ERRORS NOW */}
        {statusModal.show && statusModal.type === 'error' && (
          <div style={modalOverlayStyle}>
            <div className="modal-content" style={{...modalContentStyle, textAlign: 'center'}}>
              <div style={{ fontSize: '50px', marginBottom: '10px' }}>⚠️</div>
              
              <h2 style={{ color: '#e11d48' }}>{statusModal.title}</h2>
              <p style={{ color: 'var(--text-muted)', marginBottom: '20px' }}>{statusModal.message}</p>
        
              <button 
                onClick={() => setStatusModal({ ...statusModal, show: false })} 
                style={{
                  ...confirmBtnStyle, 
                  backgroundColor: '#3b82f6', 
                  width: '100%'
                }}
              >
                Try Again
              </button>
            </div>
          </div>
        )}

    </div> // This is the final closing div of your component
  );
}

// --- STYLES ---
const modalOverlayStyle = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.9)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 2000 };
const modalContentStyle = { backgroundColor: '#fff', padding: '24px', borderRadius: '20px', width: '95%', maxWidth: '450px', maxHeight: '90vh', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)', overflow: 'hidden' };
const summaryListStyle = { margin: '20px 0', padding: '10px 15px', backgroundColor: 'var(--surface-2)', borderRadius: '12px', border: '1px solid var(--border-color)', maxHeight: '350px', overflowY: 'auto', textAlign: 'left', WebkitOverflowScrolling: 'touch' };
const summaryRowStyle = { 
  display: 'flex', 
  justifyContent: 'space-between', 
  padding: '10px 0', 
  borderBottom: '1px solid var(--border-color)', 
  alignItems: 'center',  // <--- This centers the name and the photo
  gap: '12px' 
};
const clearAllBtnStyle = { flex: 1, backgroundColor: 'transparent', color: '#f87171', border: '1px solid #f87171', padding: '16px', borderRadius: '14px', fontWeight: 'bold', cursor: 'pointer', transition: 'all 0.2s', fontSize: '14px' };
const cancelBtnStyle = { flex: 1, padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)', color: 'var(--text-muted)', fontWeight: '600', cursor: 'pointer', backgroundColor: 'transparent' };
const confirmBtnStyle = { flex: 1, padding: '14px', borderRadius: '10px', border: 'none', color: '#fff', fontWeight: 'bold', cursor: 'pointer', transition: 'all 0.2s' };
const footerBarStyle = { position: 'fixed', bottom: 0, left: 0, right: 0, backgroundColor: '#1e293b', padding: '24px', borderTop: '1px solid #334155', zIndex: 1000 };
const submitBallotBtnStyle = { backgroundColor: '#3b82f6', color: 'white', border: 'none', padding: '16px 48px', borderRadius: '14px', fontWeight: 'bold', fontSize: '18px', cursor: 'pointer' };

const positionHeaderStyle = { 
  backgroundColor: '#1e293b', 
  color: '#ffffff',             // Changed from #3b82f6 to pure white for visibility
  padding: '12px 20px', 
  borderRadius: '10px', 
  textAlign: 'left', 
  marginBottom: '24px', 
  borderLeft: '6px solid #3b82f6',
  fontSize: '14px',             // Added for better scaling
  fontWeight: '700',            // Bold to match your sketch
  textTransform: 'uppercase'    // Makes it stand out as a header
};

const gridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '24px' };
const cardStyle = { background: '#fff', padding: '24px', borderRadius: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center', transition: 'all 0.3s' };
const imageStyle = { width: '110px', height: '110px', borderRadius: '50%', marginBottom: '16px', objectFit: 'cover', border: '4px solid #f8fafc' };
const voteButtonStyle = { width: '100%', color: 'white', border: 'none', padding: '12px', borderRadius: '10px', fontWeight: 'bold', cursor: 'pointer' };
const horizontalCardStyle = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between', // This keeps the tick box on the right
  padding: '12px 16px',
  borderRadius: '16px',
  cursor: 'pointer',
  transition: 'all 0.2s ease',
  width: '100%',
  maxWidth: '550px',
  margin: '0 auto'
};

const horizontalImageStyle = {
  width: '55px',
  height: '55px',
  borderRadius: '50%',
  objectFit: 'cover',
  border: '2px solid #475569',
  backgroundColor: '#334155'
};

const tickBoxStyle = {
  width: '28px',
  height: '28px',
  border: '2px solid',
  borderRadius: '8px',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center'
};
