import React, { useEffect, useState } from 'react';
import axios from 'axios';

export default function ITAdminDashboard({ apiBase, onLogout }) {
  const API_URL = apiBase.replace(/\/$/, '');

  const itAdminId   = sessionStorage.getItem('it_admin_id')   || '';
  const itAdminName = sessionStorage.getItem('it_admin_name') || '';

  const [activeTab, setActiveTab] = useState('add');
  const [myRequests, setMyRequests] = useState([]);
  const [loading, setLoading]       = useState(false);
  
  // --Payment states
  const [paymentMethod, setPaymentMethod] = useState('');
  const [paymentProof, setPaymentProof]   = useState(null);
  const [paymentProofPreview, setPaymentProofPreview] = useState(null);
  const [uploadingProof, setUploadingProof] = useState(false);
  
  // ── Add student form state ──
  const [addForm, setAddForm] = useState({
    student_id: '', full_name: '', phone: '', reason: ''
  });
  const [addSubmitting, setAddSubmitting] = useState(false);
  const [addError, setAddError]           = useState('');
  const [addSuccess, setAddSuccess]       = useState('');

  // ── Remove student form state ──
  const [removeForm, setRemoveForm] = useState({ student_id: '', reason: '' });
  const [removeSubmitting, setRemoveSubmitting] = useState(false);
  const [removeError, setRemoveError]           = useState('');
  const [removeSuccess, setRemoveSuccess]       = useState('');
  const [voters, setVoters]                     = useState([]);
  const [removeSearch, setRemoveSearch]         = useState('');
  const [showRemoveDropdown, setShowRemoveDropdown] = useState(false);

  // ── Cancel state ──
  const [cancelling, setCancelling] = useState({});

  //helpers
  async function uploadToCloudinary(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('upload_preset', import.meta.env.VITE_CLOUDINARY_UPLOAD_PRESET);
    const res = await axios.post(
      `https://api.cloudinary.com/v1_1/${import.meta.env.VITE_CLOUDINARY_CLOUD_NAME}/image/upload`,
      formData
    );
    return res.data.secure_url;
  }
  
  useEffect(() => {
    fetchMyRequests();
    fetchVoters();
    const interval = setInterval(fetchMyRequests, 20000);
    return () => clearInterval(interval);
  }, []);
  
  const fetchVoters = async () => {
    try {
      const res = await axios.get(`${API_URL}/admin/voters`);
      setVoters(res.data);
    } catch (e) {}
  };

  const fetchMyRequests = async () => {
    if (!itAdminId) return;
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/it-admin/students/my-requests/${encodeURIComponent(itAdminId)}`);
      setMyRequests(res.data);
    } catch (e) {
      console.error('Failed to fetch requests:', e);
    } finally {
      setLoading(false);
    }
  };

  // ── Add student ──

  const handleAddSubmit = async (e) => {
    e.preventDefault();
    setAddError('');
    setAddSuccess('');
  
    if (!addForm.student_id.trim()) { setAddError('Student ID is required.'); return; }
    if (!addForm.full_name.trim())  { setAddError('Full name is required.');  return; }
    if (!addForm.phone.trim())      { setAddError('Phone number is required.'); return; }
    if (!addForm.reason.trim())     { setAddError('Reason is required.');     return; }
    if (!paymentMethod)             { setAddError('Please select a payment method.'); return; }
    if (!paymentProof)              { setAddError('Please upload proof of payment.'); return; }
  
    setAddSubmitting(true);
    try {
      setUploadingProof(true);
      const payment_proof_url = await uploadToCloudinary(paymentProof);
      setUploadingProof(false);
  
      await axios.post(`${API_URL}/it-admin/students/request-add`, {
        student_id:        addForm.student_id.trim(),
        full_name:         addForm.full_name.trim(),
        phone:             addForm.phone.trim(),
        reason:            addForm.reason.trim(),
        requested_by:      itAdminId,
        payment_method:    paymentMethod,
        payment_proof_url,
      });
      setAddSuccess('Request submitted. Waiting for commission approval.');
      setAddForm({ student_id: '', full_name: '', phone: '', reason: '' });
      setPaymentMethod('');
      setPaymentProof(null);
      setPaymentProofPreview(null);
      fetchMyRequests();
    } catch (e) {
      setAddError(e.response?.data?.detail || 'Failed to submit request.');
    } finally {
      setAddSubmitting(false);
      setUploadingProof(false);
    }
  };
  
  // ── Remove student ──

  const handleRemoveSubmit = async (e) => {
    e.preventDefault();
    setRemoveError('');
    setRemoveSuccess('');

    if (!removeForm.student_id.trim()) { setRemoveError('Student ID is required.'); return; }
    if (!removeForm.reason.trim())     { setRemoveError('Reason is required.');     return; }

    setRemoveSubmitting(true);
    try {
      await axios.post(`${API_URL}/it-admin/students/request-remove`, {
        student_id:   removeForm.student_id.trim(),
        reason:       removeForm.reason.trim(),
        requested_by: itAdminId,
      });
      setRemoveSuccess('Request submitted. Waiting for commission approval.');
      setRemoveForm({ student_id: '', reason: '' });
      setRemoveSearch('');
      fetchMyRequests();
    } catch (e) {
      setRemoveError(e.response?.data?.detail || 'Failed to submit request.');
    } finally {
      setRemoveSubmitting(false);
    }
  };

  // ── Cancel request ──

  const handleCancel = async (changeId) => {
    const reason = window.prompt('Optional: why are you withdrawing this request?') || '';
    if (!window.confirm('Withdraw this request? This cannot be undone.')) return;

    setCancelling(prev => ({ ...prev, [changeId]: true }));
    try {
      await axios.post(`${API_URL}/it-admin/students/requests/${changeId}/cancel`, {
        requested_by:     itAdminId,
        cancelled_reason: reason,
      });
      fetchMyRequests();
    } catch (e) {
      alert(e.response?.data?.detail || 'Failed to cancel request.');
    } finally {
      setCancelling(prev => ({ ...prev, [changeId]: false }));
    }
  };

  // ── Derived ──

  const pendingCount = myRequests.filter(r => r.status === 'pending').length;

  const tabs = [
    { id: 'add',      label: '➕ Add Student' },
    { id: 'remove',   label: '➖ Remove Student' },
    { id: 'requests', label: `📋 My Requests`, count: myRequests.length },
  ];

  return (
    <div style={outerWrap}>
      <div style={container}>

        {/* ── Header ── */}
        <div style={headerFlex}>
          <div>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>💻 IT Admin Panel</h2>
            <span style={{ fontSize: '12px', opacity: 0.6 }}>
              Logged in as <strong>{itAdminName || itAdminId}</strong>
              {pendingCount > 0 && ` · ${pendingCount} pending request${pendingCount !== 1 ? 's' : ''}`}
            </span>
          </div>
          <button style={redBtn} onClick={onLogout}>Logout</button>
        </div>

        {!itAdminId && (
          <div style={{ ...infoBox, borderColor: '#e74c3c40', marginBottom: '20px' }}>
            <p style={{ margin: 0, color: '#e74c3c', fontSize: '13px' }}>
              ⚠️ Your IT admin session could not be identified. Please log out and log back in.
            </p>
          </div>
        )}

        {/* ── Tabs ── */}
        <div style={tabBar}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              style={{ ...tab, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}>
              {t.label}
              {t.count !== undefined && <span style={countPill}>{t.count}</span>}
            </button>
          ))}
        </div>

        {/* ══════════════ ADD STUDENT ══════════════ */}
        {activeTab === 'add' && (
          <div style={twoColLayout}>
            <div style={card}>
              <h4 style={cardTitle}>Request to Add a Student</h4>
              <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 16px' }}>
                This request will be sent to the Election Commission for approval before the student
                is added to the voter register. Full commission consensus is required.
              </p>

              <form onSubmit={handleAddSubmit} style={formCol}>
                <label style={lbl}>Student Registration Number *</label>
                <input style={inp} placeholder="e.g. 22/U/IED/1086/GV"
                  value={addForm.student_id}
                  onChange={e => setAddForm({ ...addForm, student_id: e.target.value })} />

                <label style={{ ...lbl, marginTop: '10px' }}>Full Name *</label>
                <input style={inp} placeholder="e.g. Ayebale Elizabeth"
                  value={addForm.full_name}
                  onChange={e => setAddForm({ ...addForm, full_name: e.target.value })} />

                <label style={{ ...lbl, marginTop: '10px' }}>Phone Number *</label>
                <input style={inp} placeholder="e.g. 0705123456"
                  value={addForm.phone}
                  onChange={e => setAddForm({ ...addForm, phone: e.target.value })} />

                <label style={{ ...lbl, marginTop: '10px' }}>Reason for Adding *</label>
                <textarea style={{ ...inp, height: '80px', resize: 'vertical' }}
                  placeholder="e.g. Student was missed during initial registration."
                  value={addForm.reason}
                  onChange={e => setAddForm({ ...addForm, reason: e.target.value })} />
                
                <label style={{ ...lbl, marginTop: '14px' }}>Payment Method *</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {['Mobile Money (MTN)', 'Mobile Money (Airtel)', 'Bank Transfer', 'Cash Receipt'].map(method => (
                    <div
                      key={method}
                      onClick={() => setPaymentMethod(method)}
                      style={{
                        padding: '10px 14px', borderRadius: '8px', cursor: 'pointer',
                        border: paymentMethod === method ? '2px solid #2ecc71' : '1px solid var(--border-color)',
                        backgroundColor: paymentMethod === method ? '#2ecc7110' : 'var(--card-bg)',
                        fontSize: '13px', color: 'var(--text-color)'
                      }}
                    >
                      {method}
                    </div>
                  ))}
                </div>
                
                <label style={{ ...lbl, marginTop: '10px' }}>Proof of Payment *</label>
                <label style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  border: '2px dashed var(--border-color)', borderRadius: '10px',
                  padding: '16px', cursor: 'pointer', minHeight: '90px'
                }}>
                  {paymentProofPreview ? (
                    <img src={paymentProofPreview} alt="Proof preview"
                      style={{ maxHeight: '150px', maxWidth: '100%', objectFit: 'contain', borderRadius: '8px' }} />
                  ) : (
                    <div style={{ textAlign: 'center', opacity: 0.5, fontSize: '13px' }}>
                      🧾 Click to upload receipt or screenshot
                    </div>
                  )}
                  <input type="file" accept="image/*,application/pdf" style={{ display: 'none' }}
                    onChange={e => {
                      const file = e.target.files[0];
                      if (!file) return;
                      setPaymentProof(file);
                      setPaymentProofPreview(URL.createObjectURL(file));
                    }} />
                </label>
                {paymentProofPreview && (
                  <button type="button"
                    style={{ ...ghostBtn, marginTop: '6px', fontSize: '12px', color: '#e74c3c' }}
                    onClick={() => { setPaymentProof(null); setPaymentProofPreview(null); }}>
                    Remove receipt
                  </button>
                )}
                
                {addError && <div style={errorBox}>⚠️ {addError}</div>}
                {addSuccess && <div style={successBox}>✅ {addSuccess}</div>}

              <button type="submit" style={{ ...greenBtn, marginTop: '14px' }} disabled={addSubmitting}>
                {uploadingProof ? '⏳ Uploading receipt…' : addSubmitting ? 'Submitting…' : '📨 Submit Add Request'}
              </button>
              </form>
            </div>
          </div>
        )}

        {/* ══════════════ REMOVE STUDENT ══════════════ */}
        {activeTab === 'remove' && (
          <div style={{ maxWidth: '540px' }}>
            <div style={card}>
              <h4 style={cardTitle}>Request to Remove a Student</h4>
              <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 16px' }}>
                Typically used when a student has not paid fees or is no longer eligible to vote.
                This request also requires full commission approval.
              </p>

              <form onSubmit={handleRemoveSubmit} style={formCol}>
                <label style={lbl}>Student Registration Number *</label>
                <div style={{ position: 'relative' }}>
                  <input
                    style={inp}
                    placeholder="Search by name or student ID…"
                    value={removeSearch}
                    onChange={e => {
                      setRemoveSearch(e.target.value);
                      setRemoveForm({ ...removeForm, student_id: '' });
                      setShowRemoveDropdown(true);
                    }}
                    onFocus={() => setShowRemoveDropdown(true)}
                  />
                  {showRemoveDropdown && removeSearch && (
                    <div style={dropdownList}>
                      {voters
                        .filter(v =>
                          v.full_name?.toLowerCase().includes(removeSearch.toLowerCase()) ||
                          v.student_id?.toLowerCase().includes(removeSearch.toLowerCase())
                        )
                        .slice(0, 8)
                        .map(v => (
                          <div
                            key={v.student_id}
                            style={dropdownItem}
                            onClick={() => {
                              setRemoveForm({ ...removeForm, student_id: v.student_id });
                              setRemoveSearch(`${v.full_name} (${v.student_id})`);
                              setShowRemoveDropdown(false);
                            }}
                          >
                            <b>{v.full_name}</b> — <span style={{ opacity: 0.6, fontSize: '12px' }}>{v.student_id}</span>
                          </div>
                        ))}
                      {voters.filter(v =>
                        v.full_name?.toLowerCase().includes(removeSearch.toLowerCase()) ||
                        v.student_id?.toLowerCase().includes(removeSearch.toLowerCase())
                      ).length === 0 && (
                        <div style={{ ...dropdownItem, opacity: 0.5, cursor: 'default' }}>No matching students.</div>
                      )}
                    </div>
                  )}
                </div>
                {removeForm.student_id && (
                  <p style={{ fontSize: '11px', color: '#2ecc71', margin: '4px 0 0' }}>
                    ✓ Selected: {removeForm.student_id}
                  </p>
                )}

                <label style={{ ...lbl, marginTop: '10px' }}>Reason for Removal *</label>
                <textarea style={{ ...inp, height: '80px', resize: 'vertical' }}
                  placeholder="e.g. Did not pay tuition fees for this semester."
                  value={removeForm.reason}
                  onChange={e => setRemoveForm({ ...removeForm, reason: e.target.value })} />

                {removeError && <div style={errorBox}>⚠️ {removeError}</div>}
                {removeSuccess && <div style={successBox}>✅ {removeSuccess}</div>}

                <button type="submit" style={{ ...redBtn, marginTop: '14px' }} disabled={removeSubmitting}>
                  {removeSubmitting ? 'Submitting…' : '📨 Submit Removal Request'}
                </button>
              </form>
            </div>
          </div>
        )}

        {/* ══════════════ MY REQUESTS ══════════════ */}
        {activeTab === 'requests' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '14px' }}>
              <button style={ghostBtn} onClick={fetchMyRequests} disabled={loading}>
                {loading ? 'Syncing…' : '🔄 Refresh'}
              </button>
            </div>

            {myRequests.length === 0 && !loading && (
              <div style={emptyState}>
                <div style={{ fontSize: '40px', marginBottom: '10px' }}>📭</div>
                <p style={{ opacity: 0.5 }}>You haven't submitted any requests yet.</p>
              </div>
            )}

            {myRequests.map(req => (
              <div key={req._id} style={appCard}>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>
                      {req.change_type === 'add' ? '➕ Add Student' : '➖ Remove Student'}
                    </b>
                    <span style={{ ...statusBadge(req.status), marginLeft: '10px' }}>
                      {req.status.toUpperCase().replace('_', ' ')}
                      {req.superadmin_override && ' · SA'}
                    </span>
                  </div>
                  <small style={{ opacity: 0.45 }}>
                    {new Date(req.requested_at).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' })}
                  </small>
                </div>

                <p style={{ margin: '8px 0 2px', fontSize: '13px', color: 'var(--text-color)' }}>
                  <b>Student:</b> {req.full_name} — <code style={{ fontSize: '12px' }}>{req.student_id}</code>
                </p>
                {req.change_type === 'add' && req.phone && (
                  <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.6 }}>
                    Phone: {req.phone}
                  </p>
                )}
                <p style={{ margin: '6px 0', fontSize: '13px', opacity: 0.8 }}>
                  <b>Reason:</b> {req.reason}
                </p>

                {req.status === 'pending' && (
                  <p style={{ margin: '6px 0 0', fontSize: '12px', opacity: 0.5 }}>
                    Votes so far: {Object.keys(req.votes || {}).length} commissioner(s) have responded.
                  </p>
                )}

                {req.status === 'cancelled' && req.cancelled_reason && (
                  <p style={{ margin: '6px 0 0', fontSize: '12px', opacity: 0.5, fontStyle: 'italic' }}>
                    Withdrawal note: {req.cancelled_reason}
                  </p>
                )}

                {req.status === 'pending' && (
                  <button
                    style={{ ...ghostBtn, marginTop: '12px', color: '#e74c3c', borderColor: '#e74c3c' }}
                    disabled={cancelling[req._id]}
                    onClick={() => handleCancel(req._id)}
                  >
                    {cancelling[req._id] ? 'Withdrawing…' : '🚫 Withdraw Request'}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  );
}

// ── Helpers ──
function statusBadge(status) {
  const map = {
    pending:        { background: '#f1c40f20', color: '#f1c40f' },
    approved:       { background: '#2ecc7120', color: '#2ecc71' },
    force_approved: { background: '#2ecc7120', color: '#2ecc71' },
    denied:         { background: '#e74c3c20', color: '#e74c3c' },
    force_denied:   { background: '#e74c3c20', color: '#e74c3c' },
    cancelled:      { background: '#95a5a620', color: '#95a5a6' },
  };
  return {
    fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
    ...(map[status] || {}),
  };
}

// ── Styles ──
const dropdownList = { position: 'absolute', top: '100%', left: 0, right: 0, backgroundColor: 'var(--card-bg)', border: '1px solid var(--border-color)', borderRadius: '8px', marginTop: '4px', maxHeight: '220px', overflowY: 'auto', zIndex: 20 };
const dropdownItem = { padding: '10px 12px', fontSize: '13px', color: 'var(--text-color)', cursor: 'pointer', borderBottom: '1px solid var(--border-color)' };
const twoColLayout = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', alignItems: 'start' };
const outerWrap   = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container   = { width: '95%', maxWidth: '1200px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const headerFlex  = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' };
const tabBar      = { display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap' };
const tab         = { background: 'none', border: 'none', padding: '10px 16px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' };
const countPill   = { fontSize: '11px', backgroundColor: 'var(--border-color)', borderRadius: '10px', padding: '1px 7px', fontWeight: '700' };
const card        = { padding: '20px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--bg-color)' };
const cardTitle   = { margin: '0 0 6px', color: 'var(--text-color)', fontSize: '15px', fontWeight: '600' };
const formCol     = { display: 'flex', flexDirection: 'column', gap: '4px' };
const lbl         = { fontSize: '12px', opacity: 0.65, fontWeight: '600' };
const inp         = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const btn         = { padding: '10px 18px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const greenBtn    = { ...btn, backgroundColor: '#2ecc71' };
const redBtn      = { ...btn, backgroundColor: '#e74c3c' };
const ghostBtn    = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const appCard     = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
const infoBox     = { padding: '12px 16px', backgroundColor: '#3498db10', borderRadius: '8px', border: '1px solid #3498db30' };
const errorBox    = { padding: '10px 14px', backgroundColor: '#e74c3c15', borderRadius: '8px', border: '1px solid #e74c3c40', color: '#e74c3c', fontSize: '12px', fontWeight: '600', marginTop: '10px' };
const successBox  = { padding: '10px 14px', backgroundColor: '#2ecc7115', borderRadius: '8px', border: '1px solid #2ecc7140', color: '#2ecc71', fontSize: '12px', fontWeight: '600', marginTop: '10px' };
const emptyState  = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
