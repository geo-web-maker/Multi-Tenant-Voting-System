import React, { useEffect, useState } from 'react';
import axios from 'axios';

export default function AdminDashboard({ apiBase, onLogout }) {
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
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [timerActive, setTimerActive] = useState(false);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);

  // Form & Upload States
  const [newCandidate, setNewCandidate] = useState({ name: '', position: '', image: null, order: 0 });
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);

  // Editing State
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ name: '', position: '', order: 0, newImage: null });

  const API_URL = apiBase.replace(/\/$/, '');

  // --- DATA FETCHING ---
  const fetchData = async () => {
    try {
      setLoading(true);
      const [voterRes, statusRes, candidateRes, balanceRes] = await Promise.all([
        axios.get(`${API_URL}/admin/voters`),
        axios.get(`${API_URL}/election-status`),
        axios.get(`${API_URL}/candidates`),
        axios.get(`${API_URL}/admin/sms-balance`).catch(() => ({ data: { balance: "N/A", currency: "" } }))
      ]);
      
      setVoters(voterRes.data);
      setCandidates(candidateRes.data);
      setSmsBalance(balanceRes.data);
      setLastRefreshed(new Date()); 

      // SYNC STATUS & CERTIFICATION
      setIsElectionOpen(statusRes.data.is_open);
      setIsCertified(statusRes.data.is_certified || false); // Sync certification from DB
      
      const savedStart = statusRes.data.start || statusRes.data.start_time;
      const savedEnd = statusRes.data.end || statusRes.data.end_time;

      if (savedStart && savedEnd) {
        setStartTime(savedStart);
        setEndTime(savedEnd);
        setTimerActive(true);
      } else {
        setTimerActive(false);
      }
    } catch (err) { 
      console.error("Sync Error:", err); 
    } finally { 
      setLoading(false); 
    }
  };

  // --- NEW: TOGGLE CERTIFICATION ACTION ---
  const handleToggleCertification = async () => {
  if (isElectionOpen) {
    alert("Stop the election before certifying results.");
    return;
  }

  const msg = isCertified 
    ? "Warning: This will remove the 'Official' stamp from the reports. Continue?" 
    : "Confirm Certification: This marks results as FINAL and BINDING. Proceed?";

  if (window.confirm(msg)) {
    try {
      // Your backend doesn't need a body; it just toggles the current value
      const res = await axios.post(`${API_URL}/admin/toggle-certification`);
      
      // We use the boolean returned by the backend to ensure UI matches DB exactly
      setIsCertified(res.data.is_certified);
      
      alert(`Results ${res.data.is_certified ? 'certified successfully' : 'de-certified'}!`);
    } catch (err) {
      console.error("Cert Error:", err);
      alert("Failed to update certification status.");
    }
  }
};

  // --- EXISTING ACTIONS ---
  const handleToggleElection = async () => {
    try {
      // Change this line to remove the body and use the response from the server
      const res = await axios.post(`${API_URL}/admin/toggle-election`);
      setIsElectionOpen(res.data.is_open);
      alert(`Election is now ${res.data.is_open ? "STARTED" : "STOPPED"}`);
    } catch (err) { 
      alert("Toggle failed. Ensure the route /admin/toggle-election exists on the backend."); 
    }
  };

  const handleScheduleTimer = async () => {
    if (!startTime || !endTime) return alert("Please set both start and end times.");
    try {
      await axios.post(`${API_URL}/admin/schedule-election`, { start: startTime, end: endTime });
      setTimerActive(true);
      alert("Election schedule has been set!");
      fetchData();
    } catch (err) { alert("Error scheduling election."); }
  };

  const handleClearSchedule = async () => {
    if (window.confirm("Remove the timer? The election will rely on the Manual Toggle only.")) {
      try {
        await axios.post(`${API_URL}/admin/clear-schedule`);
        setStartTime("");
        setEndTime("");
        setTimerActive(false);
        alert("Schedule cleared.");
        fetchData();
      } catch (err) { alert("Failed to clear schedule."); }
    }
  };

  const handleResetElection = async () => {
    if (window.confirm("⚠️ DANGER: This will delete ALL votes and reset the election. Proceed?")) {
      if (window.prompt("Type 'RESET' to confirm permanent deletion:") === "RESET") {
        try {
          await axios.post(`${API_URL}/admin/reset-election`);
          alert("Database cleared.");
          fetchData();
        } catch (err) { alert("Reset failed."); }
      }
    }
  };

  const handleImportVoters = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setImporting(true);
    try {
      const res = await axios.post(`${API_URL}/admin/import-voters`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      alert(`Import Successful! ${res.data.imported_count} records processed.`);
      fetchData();
    } catch (err) { alert("Import failed."); }
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
        formData.append("upload_preset", import.meta.env.VITE_CLOUDINARY_UPLOAD_PRESET);
        const cloudRes = await axios.post(`https://api.cloudinary.com/v1_1/${import.meta.env.VITE_CLOUDINARY_CLOUD_NAME}/image/upload`, formData);
        imageUrl = cloudRes.data.secure_url;
      }
      await axios.post(`${API_URL}/candidates`, { 
        ...newCandidate, 
        image_url: imageUrl, 
        votes: 0,
        order: parseInt(newCandidate.order) || 0 
      });
      setNewCandidate({ name: '', position: '', image: null, order: 0 });
      fetchData();
    } catch (err) { alert("Error adding candidate."); }
    finally { setUploading(false); }
  };

  const handleUpdateCandidate = async (id) => {
    setUploading(true);
    try {
      let imageUrl = null;
      if (editForm.newImage) {
        const formData = new FormData();
        formData.append("file", editForm.newImage);
        formData.append("upload_preset", import.meta.env.VITE_CLOUDINARY_UPLOAD_PRESET);
        const cloudRes = await axios.post(`https://api.cloudinary.com/v1_1/${import.meta.env.VITE_CLOUDINARY_CLOUD_NAME}/image/upload`, formData);
        imageUrl = cloudRes.data.secure_url;
      }
      await axios.put(`${API_URL}/candidates/${id}`, {
        name: editForm.name,
        position: editForm.position,
        order: parseInt(editForm.order) || 0,
        ...(imageUrl && { image_url: imageUrl })
      });
      setEditingId(null);
      fetchData();
    } catch (err) { alert("Update failed."); }
    finally { setUploading(false); }
  };

  const handleDeleteCandidate = async (id) => {
    if (window.confirm("Delete this candidate?")) {
      await axios.delete(`${API_URL}/candidates/${id}`);
      fetchData();
    }
  };

useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); 
    return () => clearInterval(interval);
  }, []);

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
    <div style={adminOuterWrapper} className="no-print">
      <div style={adminContainer} className="dashboard-shell">
        {/* HEADER */}
        <div style={headerFlexStyle}>
          <div>
            <h2 style={{ margin: 0 }}>🛡️ Admin Management</h2>
            <span style={{ fontSize: '11px', opacity: 0.5 }}>Sync: {lastRefreshed.toLocaleTimeString()}</span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button onClick={() => setIsPreviewOpen(true)} style={previewBtnStyle}>👁️ Preview Ballot</button>
            
            <button onClick={handleToggleElection} style={{ ...primaryBtnStyle, backgroundColor: isElectionOpen ? '#e67e22' : '#2ecc71' }}>
              {isElectionOpen ? "⏸ Stop Election" : "▶️ Start Election"}
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
              {isCertified ? "✅ Certified (Final)" : "⚠️ Certify Results"}
            </button>

            <button onClick={onLogout} style={logoutBtnStyle}>Logout</button>
          </div>
        </div>

        {/* SCHEDULER SECTION */}
        <div style={timerBoxStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h4 style={{ margin: 0, fontSize: '14px' }}>⏰ Schedule Election Period</h4>
            {timerActive && (
              <button onClick={handleClearSchedule} style={deleteLinkStyle}>🗑️ Reset Timer</button>
            )}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '15px', alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Start Time</label>
              <input type="datetime-local" value={startTime} onChange={e => setStartTime(e.target.value)} style={adminInputStyle} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>End Time</label>
              <input type="datetime-local" value={endTime} onChange={e => setEndTime(e.target.value)} style={adminInputStyle} />
            </div>
            <button onClick={handleScheduleTimer} style={refreshBtnStyle}>
              {timerActive ? "🔄 Update Schedule" : "Set Schedule"}
            </button>
          </div>
          {timerActive && (
            <div style={{ marginTop: '10px', padding: '8px', backgroundColor: '#2ecc7115', borderRadius: '6px', border: '1px solid #2ecc7140' }}>
              <small style={{ color: '#2ecc71', fontWeight: 'bold' }}>
                Active Schedule: {new Date(startTime).toLocaleString()} — {new Date(endTime).toLocaleString()}
              </small>
            </div>
          )}
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
                {duplicateIds.length > 0 && <p style={{ color: '#e74c3c', fontSize: '12px' }}>⚠️ Warning: {duplicateIds.length} duplicates detected!</p>}
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
                border: (smsBalance.balance < 1000) ? '1px solid #e74c3c' : '1px solid var(--border-color)',
                backgroundColor: (smsBalance.balance < 1000) ? '#e74c3c08' : 'transparent'
              }}>
                <small style={{ color: smsBalance.balance < 1000 ? '#e74c3c' : 'inherit' }}>SMS Credits</small>
                <h3 style={{ color: smsBalance.balance < 1000 ? '#e74c3c' : 'inherit' }}>
                  {smsBalance.balance} <small style={{fontSize: '10px'}}>{smsBalance.currency}</small>
                </h3>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
              <input type="text" placeholder="Search..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} style={adminInputStyle} />
              <button onClick={fetchData} style={refreshBtnStyle}>{loading ? "Syncing..." : "🔄 Refresh"}</button>
            </div>

            <div style={tableWrapperStyle}>
              <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, textAlign: 'left' }}>
                <thead style={stickyTheadStyle}>
                  <tr>
                    <th style={thStyle}>ID</th>
                    <th style={thStyle}>Name</th>
                    <th style={thStyle}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredVoters.map((v) => (
                    <tr key={v.student_id} style={trStyle}>
                      <td style={{ ...tdStyle, padding: '10px 12px' }}>
                        <code>{v.student_id}</code>
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
              <h4 style={{ color: '#d63031', margin: '0 0 10px 0' }}>🧨 Danger Zone</h4>
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
                        <img src={c.image_url} style={avatarStyle} alt="" />
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
          <div style={modalOverlayStyle}>
            <div style={modalContentStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
                <h3>Ballot Preview</h3>
                <button onClick={() => setIsPreviewOpen(false)} style={deleteLinkStyle}>Close</button>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
                {candidates.map((c, idx) => (
                  <div key={c._id} style={{ ...statCardStyle, textAlign: 'left', display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <span style={{ fontWeight: 'bold', opacity: 0.3 }}>{idx + 1}</span>
                    <img src={c.image_url} style={avatarStyle} alt="" />
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
  top: 0
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

const labelStyle = { 
  display: 'block', 
  fontSize: '11px', 
  fontWeight: 'bold', 
  marginBottom: '5px', 
  opacity: 0.6 
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

const headerFlexStyle = { display: 'flex', justifyContent: 'space-between', marginBottom: '25px', alignItems: 'center' };
const timerBoxStyle = { backgroundColor: 'var(--bg-color)', padding: '20px', borderRadius: '12px', marginBottom: '25px', border: '1px solid var(--border-color)' };
const funnelGridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '15px', marginBottom: '25px' };
const statCardStyle = { padding: '15px', border: '1px solid var(--border-color)', borderRadius: '12px', textAlign: 'center' };
const primaryBtnStyle = { padding: '10px 20px', backgroundColor: '#2ecc71', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold' };
const logoutBtnStyle = { padding: '8px 16px', backgroundColor: '#e74c3c', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer' };
const refreshBtnStyle = { padding: '10px 20px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer' };
const deleteLinkStyle = { color: '#e74c3c', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold' };
const avatarStyle = { width: '45px', height: '45px', borderRadius: '6px', objectFit: 'cover' };
const candidateRowStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '15px', borderBottom: '1px solid var(--border-color)' };
