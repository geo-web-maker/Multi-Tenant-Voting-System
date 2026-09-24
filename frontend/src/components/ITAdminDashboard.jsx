import React, { useEffect, useState } from 'react';
import api from '../api';
import { usePersistedTab } from '../session';
import { SHARED_TAB_DEFS, SharedTabPanels } from './SharedAdminPanels';
import { RosterStats, RecentActivity } from './SharedAdminPanels';
import { useToast, useConfirm, usePrompt, ScrollList } from './UIFeedback';
import usePolling from '../hooks/usePolling';
import { Icon } from './icons.jsx';
import ITAdminStudentEdit from './ITAdminStudentEdit';
import ResetOtpLimitsPanel from './ResetOtpLimitsPanel';
import useRosterStatus from '../hooks/useRosterStatus';
import { previewPhone } from '../studentEdit';
import './ITAdminDashboard.css';
import { regNo } from '../regNo';
import AdminHeader, { useLastSynced } from './AdminHeader';


export default function ITAdminDashboard({ onLogout }) {
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();

  const itAdminId   = sessionStorage.getItem('it_admin_id')   || '';
  const itAdminName = sessionStorage.getItem('it_admin_name') || '';

  const [activeTab, setActiveTab] = usePersistedTab('it_admin', 'overview');
  const [myRequests, setMyRequests] = useState([]);
  const [loading, setLoading]       = useState(false);
  const [lastSynced, markSynced]    = useLastSynced();
  
  // --Payment states
  const [paymentMethod, setPaymentMethod] = useState('');
  const [paymentProof, setPaymentProof]   = useState(null);
  const [paymentProofPreview, setPaymentProofPreview] = useState(null);
  const [uploadingProof, setUploadingProof] = useState(false);
  
  // ── Add student form state ──
  const [addForm, setAddForm] = useState({
    student_id: '', full_name: '', phones: [''], reason: ''
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
  // Signed, server-side upload via our own backend — replaces the old
  // unsigned Cloudinary preset upload that ran straight from the browser.
  async function uploadToCloudinary(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await api.post('/admin/upload-image', formData);
    return res.data.secure_url;
  }
  
  useEffect(() => {
    fetchMyRequests();
    fetchVoters();
  // Mount-only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Decisions on my requests (approved / denied) appear without a manual refresh.
  usePolling(() => fetchMyRequests({ silent: true }), 15000);
  
  const fetchVoters = async () => {
    try {
      const res = await api.get('/admin/voters');
      setVoters(res.data);
    } catch { /* non-critical: ignore */ }
  };

  const fetchMyRequests = async ({ silent = false } = {}) => {
    if (!itAdminId) return;
    if (!silent) setLoading(true);
    try {
      const res = await api.get(`/it-admin/students/my-requests/${encodeURIComponent(itAdminId)}`);
      setMyRequests(res.data);
      markSynced();
    } catch (e) {
      console.error('Failed to fetch requests:', e);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // ── Add student ──

  const updateAddPhone = (i, value) => {
    const phones = [...addForm.phones];
    phones[i] = value;
    setAddForm({ ...addForm, phones });
  };
  const addAddPhoneRow    = () => setAddForm({ ...addForm, phones: [...addForm.phones, ''] });
  const removeAddPhoneRow = (i) => setAddForm({ ...addForm, phones: addForm.phones.filter((_, idx) => idx !== i) });

  const handleAddSubmit = async (e) => {
    e.preventDefault();
    setAddError('');
    setAddSuccess('');

    const cleanPhones = addForm.phones.map(p => p.trim()).filter(Boolean);

    if (!addForm.student_id.trim()) { setAddError('Student ID is required.'); return; }
    if (!addForm.full_name.trim())  { setAddError('Full name is required.');  return; }
    if (!cleanPhones.length)        { setAddError('At least one phone number is required.'); return; }
    const invalidPhone = cleanPhones.find(p => !previewPhone(p));
    if (invalidPhone)                { setAddError(`"${invalidPhone}" is not a valid phone number.`); return; }
    if (!addForm.reason.trim())     { setAddError('Reason is required.');     return; }
    if (!paymentMethod)             { setAddError('Please select a payment method.'); return; }
    if (!paymentProof)              { setAddError('Please upload proof of payment.'); return; }
  
    setAddSubmitting(true);
    try {
      setUploadingProof(true);
      const payment_proof_url = await uploadToCloudinary(paymentProof);
      setUploadingProof(false);
  
      await api.post('/it-admin/students/request-add', {
        student_id:        addForm.student_id.trim(),
        full_name:         addForm.full_name.trim(),
        phones:            cleanPhones,
        reason:            addForm.reason.trim(),
        requested_by:      itAdminId,
        payment_method:    paymentMethod,
        payment_proof_url,
      });
      setAddSuccess('Request submitted.');
      setAddForm({ student_id: '', full_name: '', phones: [''], reason: '' });
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
      await api.post('/it-admin/students/request-remove', {
        student_id:   removeForm.student_id.trim(),
        reason:       removeForm.reason.trim(),
        requested_by: itAdminId,
      });
      setRemoveSuccess('Request submitted.');
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
    const reason = (await prompt('Optional: why are you withdrawing this request?', { placeholder: 'Reason (optional)' })) || '';
    if (!(await confirm('Withdraw this request? This cannot be undone.', { danger: true, confirmText: 'Withdraw' }))) return;

    setCancelling(prev => ({ ...prev, [changeId]: true }));
    try {
      await api.post(`/it-admin/students/requests/${changeId}/cancel`, {
        requested_by:     itAdminId,
        cancelled_reason: reason,
      });
      fetchMyRequests();
    } catch (e) {
      toast(e.response?.data?.detail || 'Failed to cancel request.', { kind: 'error' });
    } finally {
      setCancelling(prev => ({ ...prev, [changeId]: false }));
    }
  };

  // ── Derived ──

  const pendingCount = myRequests.filter(r => r.status === 'pending').length;

  const roster = useRosterStatus();
  const rosterFrozen = Boolean(roster?.frozen);   // no add / remove / import after the freeze

  const tabs = [
    // IT Admin previously had no visibility into election state at all —
    // only the three roster-change tabs. Overview is now the landing tab.
    { id: 'overview', label: <>Overview</> },
    ...(rosterFrozen ? [] : [{ id: 'add', label: <>Add Student</> }]),
    { id: 'edit',     label: <>Edit Student</> },
    ...(rosterFrozen ? [] : [{ id: 'remove', label: <>Remove Student</> }]),
    { id: 'requests', label: <>My Requests</>, count: myRequests.length },
    { id: 'reset_otp', label: <>Reset OTP</> },
    ...SHARED_TAB_DEFS,
  ];

  return (
    <div style={outerWrap} className="outer-wrap itadmin-root">
      <div style={container} className="dashboard-shell">

        {/* ── Header ── */}
        <AdminHeader
          title="IT Admin Panel"
          subtitle={<>Logged in as <strong>{itAdminName || itAdminId}</strong>{pendingCount > 0 && ` · ${pendingCount} pending request${pendingCount !== 1 ? 's' : ''}`}</>}
          lastSynced={lastSynced}
          onRefresh={() => { fetchMyRequests(); fetchVoters(); }}
          refreshing={loading}
          onLogout={onLogout}
        />

        {!itAdminId && (
          <div style={{ ...infoBox, borderColor: '#e74c3c40', marginBottom: '20px' }}>
            <p style={{ margin: 0, color: '#e74c3c', fontSize: '13px' }}>
              <Icon name="warning" /> Your IT admin session could not be identified. Please log out and log back in.
            </p>
          </div>
        )}

        {rosterFrozen && (
          <div style={{ ...infoBox, borderColor: 'var(--warning)', marginBottom: '16px' }}>
            <p style={{ margin: 0, fontSize: '13px' }}>
              Roster frozen: voters cannot be added, removed or imported. Phone and registration-number changes need approval.
            </p>
          </div>
        )}

        {/* ── Tabs ── */}
        <div style={tabBar} className="tab-scroll">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              style={{ ...tab, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}>
              {t.label}
              {t.count !== undefined && <span style={countPill}>{t.count}</span>}
            </button>
          ))}
        </div>

        {/* ══════════════ ADD STUDENT ══════════════ */}
        {activeTab === 'add' && !rosterFrozen && (
          <div className="itadmin-split">
            <div style={card}>
              <h4 style={cardTitle}>Request to Add a Student</h4>

              <form onSubmit={handleAddSubmit} style={formCol}>
                <label style={lbl}>Student Registration Number *</label>
                <input style={inp} placeholder="e.g. 22/U/IED/1086/GV"
                  value={addForm.student_id}
                  onChange={e => setAddForm({ ...addForm, student_id: e.target.value })} />

                <label style={{ ...lbl, marginTop: '10px' }}>Full Name *</label>
                <input style={inp} placeholder="e.g. Ayebale Elizabeth"
                  value={addForm.full_name}
                  onChange={e => setAddForm({ ...addForm, full_name: e.target.value })} />

                <label style={{ ...lbl, marginTop: '10px' }}>Phone Number(s) *</label>
                {addForm.phones.map((p, i) => (
                  <div key={i} style={{ display: 'flex', gap: '8px', marginTop: i ? '6px' : 0 }}>
                    <input style={{ ...inp, flex: 1 }} placeholder="e.g. 0705123456"
                      value={p}
                      onChange={e => updateAddPhone(i, e.target.value)} />
                    {addForm.phones.length > 1 && (
                      <button type="button" style={ghostBtn} onClick={() => removeAddPhoneRow(i)} aria-label="Remove phone number">
                        <Icon name="trash" />
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" style={{ ...ghostBtn, marginTop: '8px', alignSelf: 'flex-start' }} onClick={addAddPhoneRow}>
                  + Add another phone number
                </button>

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
                        padding: '10px 14px', minHeight: '44px', display: 'flex', alignItems: 'center', borderRadius: '8px', cursor: 'pointer',
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
                      <Icon name="receipt" /> Click to upload receipt or screenshot
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
                
                {addError && <div style={errorBox}><Icon name="warning" /> {addError}</div>}
                {addSuccess && <div style={successBox}><Icon name="success" /> {addSuccess}</div>}

              <button type="submit" style={{ ...greenBtn, marginTop: '14px' }} disabled={addSubmitting}>
                {uploadingProof ? <><Icon name="loading" /> Uploading receipt…</> : addSubmitting ? 'Submitting…' : <>Submit Add Request</>}
              </button>
              </form>
            </div>
            <aside style={card} className="itadmin-summary" aria-label="Live summary">
              <h4 style={cardTitle}>Summary</h4>
              {[
                ['Registration no.', regNo(addForm.student_id.trim())],
                ['Name', addForm.full_name.trim()],
                ['Phone(s)', addForm.phones.map(p => p.trim()).filter(Boolean)
                  .map(p => previewPhone(p) || `${p} (invalid)`).join(', ')],
                ['Reason', addForm.reason.trim()],
                ['Payment', paymentMethod],
                ['Receipt', paymentProof ? paymentProof.name : ''],
              ].map(([k, v]) => (
                <div key={k} className="itadmin-kv"><span>{k}</span><b>{v || '—'}</b></div>
              ))}
            </aside>
          </div>
        )}

        {/* ══════════════ EDIT STUDENT ══════════════ */}
        {activeTab === 'edit' && <ITAdminStudentEdit />}

        {/* ══════════════ RESET OTP LIMITS ══════════════ */}
        {activeTab === 'reset_otp' && <ResetOtpLimitsPanel />}

        {/* ══════════════ REMOVE STUDENT ══════════════ */}
        {activeTab === 'remove' && !rosterFrozen && (
          <div className="itadmin-split">
            <div style={card}>
              <h4 style={cardTitle}>Request to Remove a Student</h4>
              <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 16px' }}>
                Typically used when a student has not paid fees or is no longer eligible to vote.
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
                              setRemoveSearch(`${v.full_name} (${regNo(v.student_id)})`);
                              setShowRemoveDropdown(false);
                            }}
                          >
                            <b>{v.full_name}</b> — <span style={{ opacity: 0.6, fontSize: '12px' }}>{regNo(v.student_id)}</span>
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
                    <Icon name="check" /> Selected: {regNo(removeForm.student_id)}
                  </p>
                )}

                <label style={{ ...lbl, marginTop: '10px' }}>Reason for Removal *</label>
                <textarea style={{ ...inp, height: '80px', resize: 'vertical' }}
                  placeholder="e.g. Did not pay tuition fees for this semester."
                  value={removeForm.reason}
                  onChange={e => setRemoveForm({ ...removeForm, reason: e.target.value })} />

                {removeError && <div style={errorBox}><Icon name="warning" /> {removeError}</div>}
                {removeSuccess && <div style={successBox}><Icon name="success" /> {removeSuccess}</div>}

                <button type="submit" style={{ ...redBtn, marginTop: '14px' }} disabled={removeSubmitting}>
                  {removeSubmitting ? 'Submitting…' : <>Submit Removal Request</>}
                </button>
              </form>
            </div>
            <aside style={card} className="itadmin-summary" aria-label="Live summary">
              <h4 style={cardTitle}>Summary</h4>
              {[
                ['Student', removeForm.student_id ? (voters.find(v => v.student_id === removeForm.student_id)?.full_name || '') : ''],
                ['Registration no.', regNo(removeForm.student_id)],
                ['Reason', removeForm.reason.trim()],
              ].map(([k, v]) => (
                <div key={k} className="itadmin-kv"><span>{k}</span><b>{v || '—'}</b></div>
              ))}
            </aside>
          </div>
        )}

        {/* ══════════════ MY REQUESTS ══════════════ */}
        {activeTab === 'requests' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '14px' }}>
              <button style={ghostBtn} onClick={() => fetchMyRequests()} disabled={loading}>
                {loading ? 'Syncing…' : <>Refresh</>}
              </button>
            </div>

            {myRequests.length === 0 && !loading && (
              <div style={emptyState}>
                <p style={{ opacity: 0.5 }}>You haven't submitted any requests yet.</p>
              </div>
            )}

            <ScrollList>
            {myRequests.map(req => (
              <div key={req._id} style={appCard}>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>
                      {req.change_type === 'add' ? <>Add Student</> : <>Remove Student</>}
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
                  <b>Student:</b> {req.full_name} — <code style={{ fontSize: '12px' }}>{regNo(req.student_id)}</code>
                </p>
                {req.change_type === 'add' && (req.phones?.length > 0 || req.phone) && (
                  <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.6 }}>
                    Phone{(req.phones?.length || 1) > 1 ? 's' : ''}: {req.phones?.length ? req.phones.join(', ') : req.phone}
                  </p>
                )}
                <p style={{ margin: '6px 0', fontSize: '13px', opacity: 0.8 }}>
                  <b>Reason:</b> {req.reason}
                </p>

                {req.status === 'pending' && (
                  <p style={{ margin: '6px 0 0', fontSize: '12px', opacity: 0.5 }}>
                    <Icon name="loading" /> Awaiting review.
                  </p>
                )}

                {(req.status === 'approved' || req.status === 'denied') && (
                  <p style={{ margin: '6px 0 0', fontSize: '12px', opacity: 0.5 }}>
                    Decided by: {req.decided_by || '—'}
                    {req.decision_reason && ` · "${req.decision_reason}"`}
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
                    {cancelling[req._id] ? 'Withdrawing…' : <>Withdraw Request</>}
                  </button>
                )}
              </div>
            ))}
            </ScrollList>
          </div>
        )}

        {activeTab === 'overview' && (
          <div>
            {pendingCount > 0 && (
              <div style={{ ...infoBox, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '16px' }}>
                <span style={{ fontSize: '13px' }}>
                  You have <b>{pendingCount}</b> request{pendingCount !== 1 ? 's' : ''} awaiting approval.
                </span>
                <button style={ghostBtn} onClick={() => setActiveTab('requests')}>View requests</button>
              </div>
            )}
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '20px' }}>
              {!rosterFrozen && (
                <button style={greenBtn} onClick={() => setActiveTab('add')}>+ Add Student</button>
              )}
              <button style={ghostBtn} onClick={() => setActiveTab('edit')}>Edit Student</button>
              {!rosterFrozen && (
                <button style={ghostBtn} onClick={() => setActiveTab('remove')}>Remove Student</button>
              )}
            </div>
            <RosterStats />
            <RecentActivity />
          </div>
        )}
        <SharedTabPanels activeTab={activeTab} />
      </div>
    </div>
  );
}

// ── Helpers ──
function statusBadge(status) {
  const map = {
    pending:  { background: 'color-mix(in srgb, var(--warning) 20%, transparent)', color: 'var(--warning)' },
    approved: { background: 'color-mix(in srgb, var(--success) 20%, transparent)', color: 'var(--success)' },
    force_approved: { background: 'color-mix(in srgb, var(--success) 20%, transparent)', color: 'var(--success)' },
    denied:   { background: 'color-mix(in srgb, var(--danger) 20%, transparent)',  color: 'var(--danger)' },
    force_denied:   { background: 'color-mix(in srgb, var(--warning) 20%, transparent)', color: 'var(--warning)' },
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
const outerWrap   = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container   = { width: '100%', maxWidth: '1200px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const tabBar      = { display: 'flex', rowGap: '10px', columnGap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap', alignItems: 'stretch' };
const tab         = { background: 'none', border: 'none', padding: '10px 16px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px', lineHeight: '1.3', borderRadius: '6px 6px 0 0', display: 'flex', alignItems: 'center', gap: '6px' };
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
const infoBox     = { padding: '12px 16px', backgroundColor: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--info) 30%, transparent)' };
const errorBox    = { padding: '10px 14px', backgroundColor: 'color-mix(in srgb, var(--danger) 15%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--danger) 40%, transparent)', color: 'var(--danger)', fontSize: '12px', fontWeight: '600', marginTop: '10px' };
const successBox  = { padding: '10px 14px', backgroundColor: 'color-mix(in srgb, var(--success) 15%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--success) 40%, transparent)', color: 'var(--success)', fontSize: '12px', fontWeight: '600', marginTop: '10px' };
const emptyState  = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
