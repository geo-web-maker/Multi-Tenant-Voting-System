import React, { useEffect, useState } from 'react';
import api, { getErrorMessage } from '../api';
import { useToast, useConfirm, usePrompt } from './UIFeedback';
import { toggleElection, electionToggleFeedback } from '../electionControls';
import { Icon } from './icons.jsx';
import { faceCropUrl } from '../cloudinaryImage';
import usePolling from '../hooks/usePolling';
import { regNo } from '../regNo';
import AdminHeader from './AdminHeader';

export default function AdminDashboard({ onLogout }) {
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();
  // --- STATE MANAGEMENT ---
  const [voters, setVoters] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [smsBalance, setSmsBalance] = useState({ balance: 0, currency: 'UGX' });
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [isElectionOpen, setIsElectionOpen] = useState(true);
  const [isCertified, setIsCertified] = useState(false); // NEW: Certification state
  const [activeTab, setActiveTab] = useState("voters");
  const [lastRefreshed, setLastRefreshed] = useState(new Date());
  
  // Timer/Scheduling & Preview States
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);

  // Form & Upload States
  const [newCandidate, setNewCandidate] = useState({ name: '', position: '', image: null, order: 0 });
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);

  // Editing State
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ name: '', position: '', order: 0, newImage: null });

  // --- DATA FETCHING ---
  const fetchData = async ({ silent = false } = {}) => {
    try {
      if (!silent) setLoading(true);
      const [voterRes, statusRes, candidateRes, balanceRes] = await Promise.all([
        api.get(`/admin/voters`),
        api.get(`/election-status`),
        api.get(`/candidates`),
        api.get(`/admin/sms-balance`).catch(() => ({ data: { balance: "N/A", currency: "" } }))
      ]);
      
      setVoters(voterRes.data);
      setCandidates(candidateRes.data);
      setSmsBalance(balanceRes.data);
      setLastRefreshed(new Date()); 

      // SYNC STATUS & CERTIFICATION
      setIsElectionOpen(statusRes.data.is_open);
      setIsCertified(statusRes.data.is_certified || false); // Sync certification from DB
    } catch (err) { 
      console.error("Sync Error:", err); 
    } finally { 
      if (!silent) setLoading(false); 
    }
  };

  // --- NEW: TOGGLE CERTIFICATION ACTION ---
  const handleToggleCertification = async () => {
  if (isElectionOpen) {
    toast("Stop the election before certifying results.", { kind: 'error' });
    return;
  }

  const msg = isCertified 
    ? "Warning: This will remove the 'Official' stamp from the reports. Continue?" 
    : "Confirm Certification: This marks results as FINAL and BINDING. Proceed?";

  if (await confirm(msg, { danger: !isCertified })) {
    try {
      // Your backend doesn't need a body; it just toggles the current value
      const res = await api.post(`/admin/toggle-certification`);
      
      // We use the boolean returned by the backend to ensure UI matches DB exactly
      setIsCertified(res.data.is_certified);
      
      toast(`Results ${res.data.is_certified ? 'certified successfully' : 'de-certified'}!`, { kind: 'success' });
    } catch (err) {
      console.error("Cert Error:", err);
      toast(getErrorMessage(err, "Failed to update certification status."), { kind: 'error' });
    }
  }
};

  // --- EXISTING ACTIONS ---
  const handleToggleElection = async () => {
    if (!isElectionOpen && isCertified) {
      toast('Results are certified. Revoke certification before starting the election.', { kind: 'error' });
      return;
    }
    try {
      const data = await toggleElection(api, prompt);
      if (!data) return; // cancelled at the early-stop reason prompt
      setIsElectionOpen(data.is_open);
      const fb = electionToggleFeedback(data);
      toast(fb.text, { kind: fb.kind });
    } catch (err) { 
      toast(getErrorMessage(err, "Toggle failed. Ensure the route /admin/toggle-election exists on the backend."), { kind: 'error' }); 
    }
  };

  const handleResetElection = async () => {
    const proceed = await confirm(
      <><Icon name="warning" /> DANGER: This will permanently delete ALL votes and reset the election. This cannot be undone.</>,
      { danger: true, confirmText: 'Delete everything', requireText: 'RESET' }
    );
    if (proceed) {
      try {
        await api.post(`/admin/reset-election`);
        toast("Database cleared.", { kind: 'success' });
        fetchData();
      } catch (err) { toast(getErrorMessage(err, "Reset failed."), { kind: 'error' }); }
    }
  };

  const handleImportVoters = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setImporting(true);
    try {
      const res = await api.post(`/admin/import-voters`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      const { imported_count, skipped_rows, warning_count } = res.data;
      let msg = `Import Successful! ${imported_count} records processed.`;
      if (skipped_rows) msg += ` ${skipped_rows} row(s) skipped (missing/invalid data).`;
      if (warning_count) msg += ` ${warning_count} row(s) flagged for review (see server log / activity log for details, e.g. unusual phone numbers).`;
      toast(msg, { kind: 'success', duration: warning_count ? 9000 : 5000 });
      fetchData();
    } catch (err) { toast(getErrorMessage(err, "Import failed."), { kind: 'error' }); }
    finally { setImporting(false); e.target.value = null; }
  };

  const handleAddCandidate = async (e) => {
    e.preventDefault();
    setUploading(true);
    try {
      let imageUrl = "https://via.placeholder.com/150"; 
      if (newCandidate.image) {
        const formData = new FormData();
        formData.append("file", newCandidate.image);
        const uploadRes = await api.post(`/admin/upload-image`, formData);
        imageUrl = uploadRes.data.secure_url;
      }
      await api.post(`/candidates`, { 
        ...newCandidate, 
        image_url: imageUrl, 
        votes: 0,
        order: parseInt(newCandidate.order) || 0 
      });
      setNewCandidate({ name: '', position: '', image: null, order: 0 });
      fetchData();
    } catch (err) { toast(getErrorMessage(err, "Error adding candidate."), { kind: 'error' }); }
    finally { setUploading(false); }
  };

  const handleUpdateCandidate = async (id) => {
    setUploading(true);
    try {
      let imageUrl = null;
      if (editForm.newImage) {
        const formData = new FormData();
        formData.append("file", editForm.newImage);
        const uploadRes = await api.post(`/admin/upload-image`, formData);
        imageUrl = uploadRes.data.secure_url;
      }
      await api.put(`/candidates/${id}`, {
        name: editForm.name,
        position: editForm.position,
        order: parseInt(editForm.order) || 0,
        ...(imageUrl && { image_url: imageUrl })
      });
      setEditingId(null);
      fetchData();
    } catch (err) { toast(getErrorMessage(err, "Update failed."), { kind: 'error' }); }
    finally { setUploading(false); }
  };

  const handleDeleteCandidate = async (id) => {
    if (await confirm("Delete this candidate? This cannot be undone.", { danger: true, confirmText: 'Delete' })) {
      try {
        await api.delete(`/candidates/${id}`);
        fetchData();
      } catch (err) { toast(getErrorMessage(err, "Failed to delete candidate."), { kind: 'error' }); }
    }
  };

useEffect(() => { fetchData(); }, []);
  usePolling(() => fetchData({ silent: true }), 30000);

  // --- CALCULATIONS ---
  const turnout = voters.length > 0 ? ((voters.filter(v => v.has_voted).length / voters.length) * 100).toFixed(1) : 0;
  const stage1 = voters.filter(v => v.last_status === "otp_sent").length;      
  const stage2 = voters.filter(v => v.last_status === "authenticated").length; 
  const stage3 = voters.filter(v => v.has_voted || v.last_status === "completed").length; 
  const duplicateIds = voters.map(v => v.student_id).filter((id, index, array) => array.indexOf(id) !== index);
  
  const filteredVoters = voters.filter(v => 
    v.full_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    v.student_id.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div style={adminOuterWrapper} className="no-print outer-wrap">
      <div style={adminContainer} className="dashboard-shell">
        {/* HEADER */}
        <AdminHeader
          title="Admin Management"
          lastSynced={lastRefreshed}
          onRefresh={() => fetchData()}
          refreshing={loading}
          onLogout={onLogout}
          actions={<>
            <button onClick={() => setIsPreviewOpen(true)} style={previewBtnStyle}>Preview Ballot</button>
            
            <button
              onClick={handleToggleElection}
              aria-disabled={!isElectionOpen && isCertified}
              title={!isElectionOpen && isCertified ? 'Revoke certification before starting the election' : undefined}
              style={{
                ...primaryBtnStyle,
                backgroundColor: isElectionOpen ? '#e67e22' : '#2ecc71',
                opacity: !isElectionOpen && isCertified ? 0.5 : 1,
                cursor: !isElectionOpen && isCertified ? 'not-allowed' : 'pointer',
              }}>
              {isElectionOpen ? <>Stop Election</> : <>Start Election</>}
            </button>

            {/* FIXED CERTIFY BUTTON */}
            <button 
              onClick={handleToggleCertification}
              disabled={isElectionOpen}
              style={{
                padding: '10px 20px',
                backgroundColor: isCertified ? '#10b981' : '#f59e0b',
                color: 'white',
                borderRadius: '8px',
                cursor: isElectionOpen ? 'not-allowed' : 'pointer',
                opacity: isElectionOpen ? 0.5 : 1,
                border: 'none',
                fontWeight: 'bold'
              }}
            >
              {isCertified ? <>Certified (Final)</> : <>Certify Results</>}
            </button>
          </>}
        />

        {/* ELECTION STATUS */}
        <div style={timerBoxStyle}>
          <h4 style={{ margin: '0 0 10px', fontSize: '14px' }}>Election Status</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
            <span style={{
              fontSize: '12px', fontWeight: 'bold', padding: '4px 10px', borderRadius: '999px',
              backgroundColor: isElectionOpen ? '#e67e2220' : '#2ecc7120',
              color: isElectionOpen ? '#e67e22' : '#2ecc71',
            }}>
              {isElectionOpen ? 'ELECTION OPEN' : 'ELECTION CLOSED'}
            </span>
            <span style={{
              fontSize: '12px', fontWeight: 'bold', padding: '4px 10px', borderRadius: '999px',
              backgroundColor: isCertified ? '#2ecc7120' : '#f59e0b20',
              color: isCertified ? '#2ecc71' : '#f59e0b',
            }}>
              {isCertified ? 'RESULTS CERTIFIED' : 'NOT CERTIFIED'}
            </span>
          </div>
          <p style={{ fontSize: '11px', opacity: 0.6, margin: '10px 0 0' }}>
            Open/close and certify are the buttons above — they take effect immediately for
            every voter. Phase timing (when applications, campaign, voting and results each
            open or close) is configured in the Superadmin Panel's Timeline tab.
          </p>
        </div>

        {/* TABS */}
        <div style={tabContainerStyle}>
          <button onClick={() => setActiveTab("voters")} style={{ ...tabStyle, borderBottom: activeTab === "voters" ? '3px solid #2ecc71' : 'none' }}>Voters</button>
          <button onClick={() => setActiveTab("candidates")} style={{ ...tabStyle, borderBottom: activeTab === "candidates" ? '3px solid #2ecc71' : 'none' }}>Candidates</button>
        </div>

        {activeTab === "voters" ? (
          <>
            <div style={importBoxStyle}>
              <div style={{ flex: 1 }}>
                <h4 style={{ margin: 0 }}>Bulk Import Voters (JSON or CSV)</h4>
                {duplicateIds.length > 0 && <p style={{ color: '#e74c3c', fontSize: '12px' }}><Icon name="warning" /> Warning: {duplicateIds.length} duplicates detected!</p>}
              </div>
              <input type="file" accept=".csv,.json" onChange={handleImportVoters} disabled={importing} />
            </div>

            <div style={funnelGridStyle}>
              <div style={statCardStyle}><small>Step 1: OTP</small><h3>{stage1}</h3></div>
              <div style={statCardStyle}><small>Step 2: Authed</small><h3>{stage2}</h3></div>
              <div style={statCardStyle}><small>Step 3: Voted</small><h3 style={{ color: '#2ecc71' }}>{stage3}</h3></div>
              <div style={statCardStyle}><small>Turnout</small><h3>{turnout}%</h3></div>
              
              {/* SMS BALANCE CARD */}
              <div style={{
                ...statCardStyle,
                border: (typeof smsBalance.balance === 'number' && smsBalance.balance < 1000) ? '1px solid #e74c3c' : '1px solid var(--border-color)',
                backgroundColor: (typeof smsBalance.balance === 'number' && smsBalance.balance < 1000) ? '#e74c3c08' : 'transparent'
              }}>
                <small style={{ color: (typeof smsBalance.balance === 'number' && smsBalance.balance < 1000) ? '#e74c3c' : 'inherit' }}>SMS Credits</small>
                <h3 style={{ color: (typeof smsBalance.balance === 'number' && smsBalance.balance < 1000) ? '#e74c3c' : 'inherit' }}>
                  {smsBalance.error ? '—' : <>{smsBalance.balance} <small style={{fontSize: '10px'}}>{smsBalance.currency}</small></>}
                </h3>
                {smsBalance.error && <small style={{ opacity: 0.6 }}>{smsBalance.error}</small>}
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
              <input type="text" placeholder="Search..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} style={adminInputStyle} />
              <button onClick={() => fetchData()} style={refreshBtnStyle}>{loading ? "Syncing..." : <>Refresh</>}</button>
            </div>

            <div style={tableWrapperStyle}>
              <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, textAlign: 'left', tableLayout: 'fixed' }}>
                <thead style={stickyTheadStyle}>
                  <tr>
                    <th style={{ ...thStyle, width: '22%' }}>ID</th>
                    <th style={{ ...thStyle, width: '56%' }}>Name</th>
                    <th style={{ ...thStyle, width: '22%' }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredVoters.map((v) => (
                    <tr key={v.student_id} style={trStyle}>
                      <td style={{ ...tdStyle, padding: '10px 12px' }}>
                        <code>{regNo(v.student_id)}</code>
                      </td>
                      <td style={{ ...tdStyle, padding: '10px 12px' }}>
                        {v.full_name}
                      </td>
                      <td style={{ ...tdStyle, padding: '10px 12px' }}>
                        <span style={{ 
                          fontSize: '10px', 
                          padding: '4px 8px', 
                          borderRadius: '12px', 
                          fontWeight: 'bold',
                          background: v.has_voted ? '#2ecc7120' : '#f1c40f20', 
                          color: v.has_voted ? '#2ecc71' : '#f1c40f' 
                        }}>
                          {v.has_voted ? "FINISHED" : (v.last_status || "IDLE").toUpperCase()}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={dangerZoneStyle}>
              <h4 style={{ color: '#d63031', margin: '0 0 10px 0' }}>Danger Zone</h4>
              <button 
                onClick={handleResetElection} 
                disabled={isCertified} // Prevent accidental reset of certified results
                style={{ 
                  ...logoutBtnStyle, 
                  backgroundColor: '#d63031',
                  opacity: isCertified ? 0.5 : 1,
                  cursor: isCertified ? 'not-allowed' : 'pointer'
                }}
              >
                {isCertified ? "Cannot Reset Certified Election" : "Full Election Reset"}
              </button>
            </div>
          </>
        ) : (
          <div style={candidateGridStyle}>
            <div style={statCardStyle}>
              <h4 style={{ marginTop: 0 }}>Add Candidate</h4>
              <form onSubmit={handleAddCandidate} style={formStyle}>
                <input style={adminInputStyle} placeholder="Name" value={newCandidate.name} onChange={e => setNewCandidate({ ...newCandidate, name: e.target.value })} required />
                <input style={adminInputStyle} placeholder="Position" value={newCandidate.position} onChange={e => setNewCandidate({ ...newCandidate, position: e.target.value })} required />
                <input style={adminInputStyle} type="number" placeholder="Order" value={newCandidate.order} onChange={e => setNewCandidate({ ...newCandidate, order: e.target.value })} />
                <input type="file" onChange={e => setNewCandidate({ ...newCandidate, image: e.target.files[0] })} />
                <button type="submit" style={primaryBtnStyle} disabled={uploading}>{uploading ? "Saving..." : "Save Candidate"}</button>
              </form>
            </div>

            <div style={tableWrapperStyle}>
              {candidates.map(c => (
                <div key={c._id} style={candidateRowStyle}>
                  {editingId === c._id ? (
                    <div style={{ ...formStyle, width: '100%' }}>
                      <input style={adminInputStyle} value={editForm.name} onChange={e => setEditForm({ ...editForm, name: e.target.value })} />
                      <input style={adminInputStyle} value={editForm.position} onChange={e => setEditForm({ ...editForm, position: e.target.value })} />
                      <input style={adminInputStyle} type="number" value={editForm.order} onChange={e => setEditForm({ ...editForm, order: e.target.value })} />
                      <input type="file" onChange={e => setEditForm({ ...editForm, newImage: e.target.files[0] })} />
                      <div style={{ display: 'flex', gap: '10px' }}>
                        <button onClick={() => handleUpdateCandidate(c._id)} style={primaryBtnStyle}>Save</button>
                        <button onClick={() => setEditingId(null)} style={secondaryBtnStyle}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                        <img src={faceCropUrl(c.image_url, 45, 45)} style={avatarStyle} alt="" />
                        <div><b>{c.name}</b> <span style={orderBadgeStyle}>#{c.order || 0}</span><br /><small style={{ color: '#2ecc71' }}>{c.position}</small></div>
                      </div>
                      <div style={{ display: 'flex', gap: '10px' }}>
                        <button onClick={() => { setEditingId(c._id); setEditForm({ name: c.name, position: c.position, order: c.order || 0, newImage: null }); }} style={{ border: 'none', background: 'none', color: '#3498db', cursor: 'pointer' }}>Edit</button>
                        <button onClick={() => handleDeleteCandidate(c._id)} style={deleteLinkStyle}>Delete</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* PREVIEW BALLOT MODAL */}
        {isPreviewOpen && (
          <div className="overlay-fade-in" style={modalOverlayStyle}>
            <div className="panel-fade-in" style={modalContentStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
                <h3>Ballot Preview</h3>
                <button onClick={() => setIsPreviewOpen(false)} style={deleteLinkStyle}>Close</button>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
                {candidates.map((c, idx) => (
                  <div key={c._id} style={{ ...statCardStyle, textAlign: 'left', display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <span style={{ fontWeight: 'bold', opacity: 0.3 }}>{idx + 1}</span>
                    <img src={faceCropUrl(c.image_url, 45, 45)} style={avatarStyle} alt="" />
                    <div><div style={{ fontWeight: 'bold' }}>{c.name}</div><small>{c.position}</small></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- STYLES ---
// --- UPDATED ADMIN STYLES ---

// --- ADMIN DASHBOARD STYLES (CLEANED) ---

const adminOuterWrapper = { 
  width: '100%', 
  minHeight: '100vh', 
  display: 'flex', 
  justifyContent: 'center', 
  backgroundColor: 'var(--bg-color)', 
  padding: '20px' 
};

const adminContainer = { 
  width: '95%', 
  maxWidth: '1200px', 
  backgroundColor: 'var(--card-bg)', 
  borderRadius: '16px', 
  padding: '30px', 
  border: '1px solid var(--border-color)' 
};

const tableWrapperStyle = {
  maxHeight: '550px', 
  overflowY: 'auto', 
  borderRadius: '12px',
  border: '1px solid var(--border-color)',
  position: 'relative',
  backgroundColor: 'var(--card-bg)',
  marginBottom: '20px'
};

const stickyTheadStyle = {
  position: 'sticky',
  top: 0, 
  zIndex: 10,
  backgroundColor: '#1e293b', 
};

const thStyle = {
  padding: '12px 15px',
  textAlign: 'left',
  color: '#ffffff',
  fontSize: '11px',
  textTransform: 'uppercase',
  borderBottom: '2px solid #334155',
  position: 'sticky',
  top: 0,
  whiteSpace: 'nowrap'
};

const tdStyle = { 
  padding: '12px 15px', 
  borderBottom: '1px solid var(--border-color)',
  color: 'var(--text-color)',
  fontSize: '14px'
};

const trStyle = { 
  transition: 'background 0.2s',
  ':hover': { backgroundColor: '#ffffff05' } 
};

const previewBtnStyle = { 
  padding: '8px 16px', 
  background: 'none', 
  color: '#3498db', 
  border: '1px solid #3498db', 
  borderRadius: '6px', 
  cursor: 'pointer', 
  fontWeight: 'bold' 
};

const modalOverlayStyle = { 
  position: 'fixed', 
  top: 0, 
  left: 0, 
  right: 0, 
  bottom: 0, 
  backgroundColor: 'rgba(0,0,0,0.85)', 
  display: 'flex', 
  justifyContent: 'center', 
  alignItems: 'center', 
  zIndex: 1000 
};

const modalContentStyle = { 
  backgroundColor: 'var(--card-bg)', 
  padding: '30px', 
  borderRadius: '16px', 
  width: '90%', 
  maxWidth: '700px', 
  maxHeight: '85vh', 
  overflowY: 'auto' 
};

const secondaryBtnStyle = { 
  padding: '10px 20px', 
  background: 'none', 
  color: 'var(--text-color)', 
  border: '1px solid var(--border-color)', 
  borderRadius: '8px' 
};

const tabContainerStyle = { 
  display: 'flex', 
  gap: '20px', 
  marginBottom: '20px', 
  borderBottom: '1px solid var(--border-color)' 
};

const tabStyle = { 
  background: 'none', 
  border: 'none', 
  padding: '10px 20px', 
  cursor: 'pointer', 
  fontWeight: 'bold', 
  color: 'var(--text-color)' 
};

const importBoxStyle = { 
  display: 'flex', 
  alignItems: 'center', 
  padding: '20px', 
  border: '1px dashed #2ecc71', 
  borderRadius: '12px', 
  marginBottom: '25px', 
  gap: '20px' 
};

const adminInputStyle = { 
  flex: 1, 
  padding: '12px', 
  borderRadius: '8px', 
  border: '1px solid var(--border-color)', 
  backgroundColor: 'var(--bg-color)', 
  color: 'var(--text-color)' 
};

const dangerZoneStyle = { 
  marginTop: '40px', 
  padding: '20px', 
  border: '1px solid #ff7675', 
  borderRadius: '12px' 
};

const candidateGridStyle = { 
  display: 'grid', 
  gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', 
  gap: '25px' 
};

const formStyle = { 
  display: 'flex', 
  flexDirection: 'column', 
  gap: '10px' 
};

const orderBadgeStyle = { 
  marginLeft: '8px', 
  fontSize: '10px', 
  backgroundColor: 'rgba(52, 152, 219, 0.1)', 
  color: '#3498db', 
  padding: '2px 6px', 
  borderRadius: '4px' 
};

const timerBoxStyle = { backgroundColor: 'var(--bg-color)', padding: '20px', borderRadius: '12px', marginBottom: '25px', border: '1px solid var(--border-color)' };
const funnelGridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '15px', marginBottom: '25px' };
const statCardStyle = { padding: '15px', border: '1px solid var(--border-color)', borderRadius: '12px', textAlign: 'center' };
const primaryBtnStyle = { padding: '10px 20px', backgroundColor: '#2ecc71', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold' };
const logoutBtnStyle = { padding: '8px 16px', backgroundColor: '#e74c3c', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer' };
const refreshBtnStyle = { padding: '10px 20px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer' };
const deleteLinkStyle = { color: '#e74c3c', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold' };
const avatarStyle = { width: '45px', height: '45px', borderRadius: '6px', objectFit: 'cover' };
const candidateRowStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '15px', borderBottom: '1px solid var(--border-color)' };
