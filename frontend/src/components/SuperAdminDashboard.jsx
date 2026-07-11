import React, { useEffect, useState } from 'react';
import axios from 'axios';
import api from '../api';

// Reuse Cloudinary upload helper
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

export default function SuperAdminDashboard({ onLogout }) {

  const [activeTab, setActiveTab] = useState('candidates');

  // --- Branding state ---
  const [branding, setBranding] = useState({ logo_url: '', primary_color: '#003366', accent_color: '#f1c40f', org_name: '', university_name: '', university_logo_url: '', commissioner_name: '', support_phone: '', support_pdf_url: '', cc_list: [] });
  const [brandSaving, setBrandSaving] = useState(false);

  // --- Positions state ---
  const [positions, setPositions]   = useState([]);
  const [newPosition, setNewPosition] = useState({ title: '', description: '', order: 0 });
  const [posLoading, setPosLoading]   = useState(false);

  // --- Candidates state (mirrored from AdminDashboard) ---
  const [candidates, setCandidates] = useState([]);
  const [newCandidate, setNewCandidate] = useState({ name: '', position: '', image: null, order: 0 });
  const [uploading, setUploading]   = useState(false);
  const [editingId, setEditingId]   = useState(null);
  const [editForm, setEditForm]     = useState({ name: '', position: '', order: 0, newImage: null });

  // --- Applications state ---
  const [applications, setApplications] = useState([]);
  const [appsLoading, setAppsLoading]   = useState(false);
  const [appFilter, setAppFilter]       = useState('all');

  // --- Commissioners state ---
  const [voters, setVoters]             = useState([]);
  const [commissioners, setCommissioners] = useState([]);
  const [voterSearch, setVoterSearch]   = useState('');
  
  // --- Voters / election state ---
  const [electionVoters, setElectionVoters] = useState([]);
  const [isElectionOpen, setIsElectionOpen] = useState(true);
  const [isCertified, setIsCertified]       = useState(false);
  const [startTime, setStartTime]           = useState('');
  const [endTime, setEndTime]               = useState('');
  const [timerActive, setTimerActive]       = useState(false);
  const [importing, setImporting]           = useState(false);
  const [voterSearch2, setVoterSearch2]     = useState('');
  const [loading, setLoading]               = useState(false);
  const [lastRefreshed, setLastRefreshed]   = useState(new Date());

  //---IT Admin and auditlog---
  const [itAdmins, setItAdmins]             = useState([]);
  const [itAdminSearch, setItAdminSearch]   = useState('');
  const [studentChanges, setStudentChanges] = useState([]);
  const [scFilter, setScFilter]             = useState('all');
  const [auditLog, setAuditLog]             = useState([]);
  const [auditFilter, setAuditFilter]       = useState('');
  const [auditLoading, setAuditLoading]     = useState(false);
  const [itCredEmail, setItCredEmail]   = useState({});   // { student_id: email }
  const [commCredEmail, setCommCredEmail] = useState({}); // { student_id: email }
  const [resetting, setResetting]       = useState({});   // { student_id: bool }
  const [saDirectAdd, setSaDirectAdd]       = useState({ student_id: '', full_name: '', phone: '', reason: '', requested_by: 'superadmin' });
  const [saDirectRemove, setSaDirectRemove] = useState({ student_id: '', reason: '', requested_by: 'superadmin' });

  //--Financial Controllers, Overseers, Organizations--
  const [financialControllers, setFinancialControllers] = useState([]);
  const [overseers, setOverseers]                       = useState([]);
  const [organizations, setOrganizations]                = useState([]);
  const [fcCredEmail, setFcCredEmail]     = useState({}); // { student_id: email }
  const [ovCredEmail, setOvCredEmail]     = useState({}); // { student_id: email }
  const [fcSearch, setFcSearch]           = useState('');
  const [ovSearch, setOvSearch]           = useState('');
  const [orgForm, setOrgForm]             = useState({ name: '', slug: '' });
  const [orgCreating, setOrgCreating]     = useState(false);

  //--Remove Students--
  const [removeSearch, setRemoveSearch]         = useState('');
  const [showRemoveDropdown, setShowRemoveDropdown] = useState(false);
  
  // ── Fetch helpers ──

  const handleSetCommissionerCredentials = async (studentId) => {
    const email = commCredEmail[studentId];
    if (!email) {
      alert('Email is required.');
      return;
    }
    try {
      const res = await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/set-credentials`, {
        email
      });
      alert(res.data.sms_notified
        ? 'Email saved. A temporary password was sent via SMS.'
        : 'Email saved, but SMS notification failed to send.');
      setCommCredEmail(prev => ({ ...prev, [studentId]: '' }));
      fetchCommissioners();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

  const handleResetCommissionerPassword = async (studentId) => {
    if (!window.confirm('Send a new temporary password to this commissioner via SMS?')) return;
    setResetting(prev => ({ ...prev, [studentId]: true }));
    try {
      const res = await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/reset-password`);
      alert(res.data.sms_notified
        ? 'New temporary password sent via SMS.'
        : 'Password reset, but SMS failed to send.');
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
    finally { setResetting(prev => ({ ...prev, [studentId]: false })); }
  };
  
  const fetchBranding = async () => {
    try {
      const res = await api.get(`/superadmin/branding`);
      setBranding(res.data);
    } catch (e) { /* use defaults */ }
  };

  const fetchPositions = async () => {
    try {
      const res = await api.get(`/positions`);
      setPositions(res.data);
    } catch (e) {}
  };

  const fetchCandidates = async () => {
    try {
      const res = await api.get(`/candidates`);
      setCandidates(res.data);
    } catch (e) {}
  };

  const fetchApplications = async () => {
    setAppsLoading(true);
    try {
      const res = await api.get(`/admin/applications`);
      setApplications(res.data);
    } catch (e) {}
    finally { setAppsLoading(false); }
  };

  const fetchCommissioners = async () => {
    try {
      const res = await api.get(`/superadmin/commissioners`);
      setCommissioners(res.data);
    } catch (e) {}
  };

  const fetchElectionData = async () => {
    setLoading(true);
    try {
      const [voterRes, statusRes] = await Promise.all([
        api.get(`/admin/voters`),
        api.get(`/election-status`),
      ]);
      setElectionVoters(voterRes.data);
      setIsElectionOpen(statusRes.data.is_open);
      setIsCertified(statusRes.data.is_certified || false);
      const s = statusRes.data.start || statusRes.data.start_time;
      const e = statusRes.data.end   || statusRes.data.end_time;
      if (s && e) { setStartTime(s); setEndTime(e); setTimerActive(true); }
      else { setTimerActive(false); }
      setLastRefreshed(new Date());
    } catch (e) {}
    finally { setLoading(false); }
  };

const fetchVotersList = async () => {
    try {
      const res = await api.get(`/admin/voters`);
      setVoters(res.data);
    } catch (e) {}
  };

  const fetchFinancialControllers = async () => {
    try {
      const res = await api.get('/superadmin/financial-controllers');
      setFinancialControllers(res.data);
    } catch (e) {}
  };

  const fetchOverseers = async () => {
    try {
      const res = await api.get('/superadmin/overseers');
      setOverseers(res.data);
    } catch (e) {}
  };

  const fetchOrganizations = async () => {
    try {
      const res = await api.get('/superadmin/orgs');
      setOrganizations(res.data);
    } catch (e) {}
  };

  useEffect(() => {
    fetchBranding();
    fetchPositions();
    fetchCandidates();
    fetchApplications();
    fetchCommissioners();
    fetchElectionData();
    fetchVotersList();
    fetchItAdmins();
    fetchStudentChanges();
    fetchFinancialControllers();
    fetchOverseers();
    fetchOrganizations();
    const interval = setInterval(() => {
      fetchCandidates();
      fetchApplications();
      fetchElectionData();
    }, 30000);
    return () => clearInterval(interval);
  }, []);
  
  // ── Branding ──

  const handleSaveBranding = async () => {
    setBrandSaving(true);
    try {
      await api.post(`/superadmin/branding`, branding);
      // Apply immediately without reload
      document.documentElement.style.setProperty('--brand-primary', branding.primary_color);
      document.documentElement.style.setProperty('--brand-accent',  branding.accent_color);
      alert('Branding saved!');
    } catch (e) { alert('Failed to save branding.'); }
    finally { setBrandSaving(false); }
  };

  // ── Positions ──

  const handleAddPosition = async () => {
    if (!newPosition.title.trim()) return alert('Position title required.');
    setPosLoading(true);
    try {
      await api.post(`/positions`, newPosition);
      setNewPosition({ title: '', description: '', order: 0 });
      fetchPositions();
    } catch (e) { alert('Failed to add position.'); }
    finally { setPosLoading(false); }
  };

  const handleDeletePosition = async (id) => {
    if (!window.confirm('Delete this position? Existing candidates under this position are unaffected.')) return;
    try {
      await api.delete(`/positions/${id}`);
      fetchPositions();
    } catch (e) { alert('Failed to delete position.'); }
  };

  // ── Candidates ──

  const handleAddCandidate = async (e) => {
    e.preventDefault();
    setUploading(true);
    try {
      let imageUrl = 'https://via.placeholder.com/150';
      if (newCandidate.image) imageUrl = await uploadToCloudinary(newCandidate.image);
      await api.post(`/candidates`, {
        name: newCandidate.name,
        position: newCandidate.position,
        image_url: imageUrl,
        order: parseInt(newCandidate.order) || 0,
      });
      setNewCandidate({ name: '', position: '', image: null, order: 0 });
      fetchCandidates();
    } catch (e) { alert('Error adding candidate.'); }
    finally { setUploading(false); }
  };

  const handleUpdateCandidate = async (id) => {
    setUploading(true);
    try {
      let imageUrl = null;
      if (editForm.newImage) imageUrl = await uploadToCloudinary(editForm.newImage);
      await api.put(`/candidates/${id}`, {
        name:     editForm.name,
        position: editForm.position,
        order:    parseInt(editForm.order) || 0,
        ...(imageUrl && { image_url: imageUrl }),
      });
      setEditingId(null);
      fetchCandidates();
    } catch (e) { alert('Update failed.'); }
    finally { setUploading(false); }
  };

  const handleRemoveCandidateOverride = async (candidateId) => {
    if (!window.confirm('Remove this candidate instantly from the ballot?')) return;
    try {
      await api.post(`/superadmin/candidates/${candidateId}/remove`);
      fetchCandidates();
      fetchApplications();
    } catch (e) { alert('Failed to remove candidate.'); }
  };

  // ── Applications ──

  const handleForceApprove = async (appId) => {
    if (!window.confirm('Force-approve this application instantly? The candidate will appear on the ballot immediately.')) return;
    try {
      await api.post(`/superadmin/applications/${appId}/force-approve`);
      fetchApplications();
      fetchCandidates();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

  const handleForceDeny = async (appId) => {
    if (!window.confirm('Force-deny this application?')) return;
    try {
      await api.post(`/superadmin/applications/${appId}/force-deny`);
      fetchApplications();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

  // ── Commissioners ──

  const handleToggleCommissioner = async (studentId) => {
    try {
      const res = await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/toggle`);
      alert(`${studentId} is now ${res.data.is_commissioner ? 'a commissioner' : 'no longer a commissioner'}.`);
      fetchCommissioners();
      fetchVotersList();
    } catch (e) { alert(e.response?.data?.detail || 'Failed to toggle commissioner.'); }
  };

  const handleSetChief = async (studentId) => {
  await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/set-chief`);
  fetchCommissioners();
};

const handleClearChief = async (studentId) => {
  await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/clear-chief`);
  fetchCommissioners();
};

const handleSetRole = async (studentId, role) => {
  await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/set-role`, { role });
  fetchCommissioners();
};

const handleSetFinanceCommissioner = async (studentId) => {
  try {
    await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/set-finance-commissioner`);
    fetchCommissioners();
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
};

const handleClearFinanceCommissioner = async (studentId) => {
  await api.post(`/superadmin/commissioners/${encodeURIComponent(studentId)}/clear-finance-commissioner`);
  fetchCommissioners();
};

// ── Financial Controllers ──

const handleToggleFinancialController = async (studentId) => {
  try {
    const res = await api.post(`/superadmin/financial-controllers/${encodeURIComponent(studentId)}/toggle`);
    alert(`${studentId} is now ${res.data.is_financial_controller ? 'a Financial Controller' : 'no longer a Financial Controller'}.`);
    fetchFinancialControllers();
    fetchVotersList();
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
};

const handleSetFinancialControllerCredentials = async (studentId) => {
  const email = fcCredEmail[studentId];
  if (!email) { alert('Email is required.'); return; }
  try {
    const res = await api.post(`/superadmin/financial-controllers/${encodeURIComponent(studentId)}/set-credentials`, { email });
    alert(res.data.sms_notified
      ? 'Email saved. A temporary password was sent via SMS.'
      : 'Email saved, but SMS notification failed to send.');
    setFcCredEmail(prev => ({ ...prev, [studentId]: '' }));
    fetchFinancialControllers();
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
};

const handleResetFinancialControllerPassword = async (studentId) => {
  if (!window.confirm('Send a new temporary password to this Financial Controller via SMS?')) return;
  setResetting(prev => ({ ...prev, [studentId]: true }));
  try {
    const res = await api.post(`/superadmin/financial-controllers/${encodeURIComponent(studentId)}/reset-password`);
    alert(res.data.sms_notified
      ? 'New temporary password sent via SMS.'
      : 'Password reset, but SMS failed to send.');
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  finally { setResetting(prev => ({ ...prev, [studentId]: false })); }
};

// ── Overseers ──

const handleToggleOverseer = async (studentId) => {
  try {
    const res = await api.post(`/superadmin/overseers/${encodeURIComponent(studentId)}/toggle`);
    alert(`${studentId} is now ${res.data.is_overseer ? 'an Overseer' : 'no longer an Overseer'}.`);
    fetchOverseers();
    fetchVotersList();
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
};

const handleSetOverseerCredentials = async (studentId) => {
  const email = ovCredEmail[studentId];
  if (!email) { alert('Email is required.'); return; }
  try {
    const res = await api.post(`/superadmin/overseers/${encodeURIComponent(studentId)}/set-credentials`, { email });
    alert(res.data.sms_notified
      ? 'Email saved. A temporary password was sent via SMS.'
      : 'Email saved, but SMS notification failed to send.');
    setOvCredEmail(prev => ({ ...prev, [studentId]: '' }));
    fetchOverseers();
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
};

const handleResetOverseerPassword = async (studentId) => {
  if (!window.confirm('Send a new temporary password to this Overseer via SMS?')) return;
  setResetting(prev => ({ ...prev, [studentId]: true }));
  try {
    const res = await api.post(`/superadmin/overseers/${encodeURIComponent(studentId)}/reset-password`);
    alert(res.data.sms_notified
      ? 'New temporary password sent via SMS.'
      : 'Password reset, but SMS failed to send.');
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  finally { setResetting(prev => ({ ...prev, [studentId]: false })); }
};

// ── Organizations ──

const handleCreateOrg = async (e) => {
  e.preventDefault();
  if (!orgForm.name.trim()) { alert('Organization name is required.'); return; }
  setOrgCreating(true);
  try {
    const res = await api.post('/superadmin/orgs', { name: orgForm.name.trim(), slug: orgForm.slug.trim() });
    alert(`Organization "${res.data.name}" provisioned with slug "${res.data.slug}". Set VITE_ORG_SLUG=${res.data.slug} in that org's frontend deployment.`);
    setOrgForm({ name: '', slug: '' });
    fetchOrganizations();
  } catch (e) { alert(e.response?.data?.detail || 'Failed to create organization.'); }
  finally { setOrgCreating(false); }
};

  // ── Election controls ──

  const handleToggleElection = async () => {
    try {
      const res = await api.post(`/admin/toggle-election`);
      setIsElectionOpen(res.data.is_open);
      alert(`Election is now ${res.data.is_open ? 'OPEN' : 'CLOSED'}.`);
    } catch (e) { alert('Toggle failed.'); }
  };

  const handleToggleCertification = async () => {
    if (isElectionOpen) { alert('Stop the election before certifying results.'); return; }
    const msg = isCertified
      ? "Remove the 'Official' stamp from results?"
      : 'Mark results as FINAL and BINDING?';
    if (!window.confirm(msg)) return;
    try {
      const res = await api.post(`/admin/toggle-certification`);
      setIsCertified(res.data.is_certified);
      alert(`Results ${res.data.is_certified ? 'certified' : 'de-certified'}.`);
    } catch (e) { alert('Failed.'); }
  };

  const handleScheduleTimer = async () => {
    if (!startTime || !endTime) { alert('Set both start and end times.'); return; }
    try {
      await api.post(`/admin/schedule-election`, { start: startTime, end: endTime });
      setTimerActive(true);
      alert('Schedule saved!');
    } catch (e) { alert('Scheduling failed.'); }
  };

  const handleClearSchedule = async () => {
    if (!window.confirm('Clear the schedule?')) return;
    try {
      await api.post(`/admin/clear-schedule`);
      setStartTime(''); setEndTime(''); setTimerActive(false);
    } catch (e) { alert('Failed to clear schedule.'); }
  };

  const handleResetElection = async () => {
    if (!window.confirm('⚠️ DANGER: Delete ALL votes and reset?')) return;
    if (window.prompt("Type 'RESET' to confirm:") !== 'RESET') return;
    try {
      await api.post(`/admin/reset-election`);
      alert('Election reset.');
      fetchElectionData();
    } catch (e) { alert('Reset failed.'); }
  };

  const handleImportVoters = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    setImporting(true);
    try {
      const res = await api.post(`/admin/import-voters`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      alert(`Imported ${res.data.imported_count} voters.`);
      fetchElectionData();
      fetchVotersList();
    } catch (e) { alert('Import failed.'); }
    finally { setImporting(false); e.target.value = null; }
  };
  
  //--IT Admin changes
  const fetchItAdmins = async () => {
  try {
      const res = await api.get(`/superadmin/it-admins`);
      setItAdmins(res.data);
    } catch (e) {}
  };

const fetchStudentChanges = async () => {
  try {
      const res = await api.get(`/superadmin/student-changes`);
      setStudentChanges(res.data);
    } catch (e) {}
  };

const fetchAuditLog = async () => {
  setAuditLoading(true);
  try {
      const url = auditFilter
        ? `/superadmin/audit-log?action=${auditFilter}`
        : `/superadmin/audit-log`;
      const res = await api.get(url);
      setAuditLog(res.data);
    } catch (e) {}
    finally { setAuditLoading(false); }
  };

  const handleToggleItAdmin = async (studentId) => {
  try {
      const res = await api.post(`/superadmin/it-admins/${encodeURIComponent(studentId)}/toggle`);
      alert(`${studentId} is now ${res.data.is_it_admin ? 'an IT admin' : 'no longer an IT admin'}.`);
      fetchItAdmins();
      fetchVotersList();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

const handleSetItAdminCredentials = async (studentId) => {
  const email = itCredEmail[studentId];
  if (!email) {
    alert('Email is required.');
    return;
  }
  try {
    const res = await api.post(`/superadmin/it-admins/${encodeURIComponent(studentId)}/set-credentials`, {
      email
    });
    alert(res.data.sms_notified
      ? 'Email saved. A temporary password was sent via SMS.'
      : 'Email saved, but SMS notification failed to send.');
    setItCredEmail(prev => ({ ...prev, [studentId]: '' }));
    fetchItAdmins();
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
};

const handleResetItAdminPassword = async (studentId) => {
  if (!window.confirm('Send a new temporary password to this IT admin via SMS?')) return;
  setResetting(prev => ({ ...prev, [studentId]: true }));
  try {
    const res = await api.post(`/superadmin/it-admins/${encodeURIComponent(studentId)}/reset-password`);
    alert(res.data.sms_notified
      ? 'New temporary password sent via SMS.'
      : 'Password reset, but SMS failed to send.');
  } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  finally { setResetting(prev => ({ ...prev, [studentId]: false })); }
};

const handleForceStudentChange = async (changeId, action) => {
  const endpoint = action === 'approve'
      ? `/superadmin/student-changes/${changeId}/force-approve`
      : `/superadmin/student-changes/${changeId}/force-deny`;
    if (!window.confirm(`Force ${action} this request?`)) return;
    try {
      await api.post(endpoint);
      fetchStudentChanges();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

const handleSuperAdminAddStudent = async (e) => {
  e.preventDefault();
  // use a separate state for this form — add useState for saDirectAdd
  try {
      await api.post(`/superadmin/students/add`, saDirectAdd);
      alert('Student added.');
      setSaDirectAdd({ student_id: '', full_name: '', phone: '', reason: '' });
      fetchElectionData();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

const handleSuperAdminRemoveStudent = async () => {
  if (!window.confirm('Remove this student from the voter register?')) return;
  try {
      await api.post(`/superadmin/students/remove`, saDirectRemove);
      alert('Student removed.');
      setSaDirectRemove({ student_id: '', reason: '' });
      setRemoveSearch('');
      fetchElectionData();
    } catch (e) { alert(e.response?.data?.detail || 'Failed.'); }
  };

  // ── Derived ──

  const filteredVoters = electionVoters.filter(v =>
    v.full_name?.toLowerCase().includes(voterSearch2.toLowerCase()) ||
    v.student_id?.toLowerCase().includes(voterSearch2.toLowerCase())
  );
  const commisssionerIds = new Set(commissioners.map(c => c.student_id));
  const filteredVoterList = voters.filter(v =>
    v.full_name?.toLowerCase().includes(voterSearch.toLowerCase()) ||
    v.student_id?.toLowerCase().includes(voterSearch.toLowerCase())
  );
  const filteredApps = appFilter === 'all'
    ? applications
    : applications.filter(a => a.status === appFilter);

  const turnout = electionVoters.length > 0
    ? ((electionVoters.filter(v => v.has_voted).length / electionVoters.length) * 100).toFixed(1)
    : 0;

  const tabs = [
    { id: 'candidates',   label: '🏅 Candidates' },
    { id: 'applications', label: '📋 Applications' },
    { id: 'commissioners',label: '🏛️ Commission' },
    { id: 'voters',       label: '🗳️ Voters' },
    { id: 'positions',    label: '📌 Positions' },
    { id: 'branding',     label: '🎨 Branding' },
    { id: 'election',     label: '⚙️ Election' },
    { id: 'it_admins',  label: '💻 IT Admins' },
    { id: 'student_changes', label: '👥 Student Changes' },
    { id: 'financial_controllers', label: '💰 Financial Controllers' },
    { id: 'overseers',  label: '👁️ Overseers' },
    { id: 'organizations', label: '🏢 Organizations' },
    { id: 'audit_log',  label: '📋 Audit Log' },
  ];

  return (
    <div style={outerWrap}>
      <div style={container}>

        {/* ── Header ── */}
        <div style={headerFlex}>
          <div>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>⚡ Superadmin Panel</h2>
            <span style={{ fontSize: '11px', opacity: 0.5 }}>
              Sync: {lastRefreshed.toLocaleTimeString()}
            </span>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={handleToggleElection}
              style={{ ...btn, backgroundColor: isElectionOpen ? '#e67e22' : '#2ecc71' }}
            >
              {isElectionOpen ? '⏸ Stop Election' : '▶️ Start Election'}
            </button>
            <button
              onClick={handleToggleCertification}
              disabled={isElectionOpen}
              style={{
                ...btn,
                backgroundColor: isCertified ? '#10b981' : '#f59e0b',
                opacity: isElectionOpen ? 0.5 : 1,
                cursor: isElectionOpen ? 'not-allowed' : 'pointer',
              }}
            >
              {isCertified ? '✅ Certified' : '⚠️ Certify Results'}
            </button>
            <button onClick={onLogout} style={{ ...btn, backgroundColor: '#e74c3c' }}>Logout</button>
          </div>
        </div>

        {/* ── Tabs ── */}
        <div style={tabBar}>
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{ ...tab, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ══════════════ CANDIDATES TAB ══════════════ */}
        {activeTab === 'candidates' && (
          <div style={twoCol}>
            <div style={card}>
              <h4 style={cardTitle}>Add Candidate Directly</h4>
              <form onSubmit={handleAddCandidate} style={formCol}>
                <input style={inp} placeholder="Full name" value={newCandidate.name}
                  onChange={e => setNewCandidate({ ...newCandidate, name: e.target.value })} required />
                <select style={inp} value={newCandidate.position}
                  onChange={e => setNewCandidate({ ...newCandidate, position: e.target.value })} required>
                  <option value="">— Select position —</option>
                  {positions.map(p => (
                    <option key={p._id} value={p.title}>{p.title}</option>
                  ))}
                </select>
                <input style={inp} type="number" placeholder="Display order (0 = first)"
                  value={newCandidate.order}
                  onChange={e => setNewCandidate({ ...newCandidate, order: e.target.value })} />
                <label style={fileLabel}>
                  Photo: <input type="file" accept="image/*"
                    onChange={e => setNewCandidate({ ...newCandidate, image: e.target.files[0] })} />
                </label>
                <button type="submit" style={greenBtn} disabled={uploading}>
                  {uploading ? 'Uploading…' : '+ Add to Ballot'}
                </button>
              </form>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <h4 style={{ ...cardTitle, marginBottom: '5px' }}>
                Current Ballot ({candidates.length} candidates)
              </h4>
              {candidates.map(c => (
                <div key={c._id} style={rowCard}>
                  {editingId === c._id ? (
                    <div style={{ ...formCol, width: '100%' }}>
                      <input style={inp} value={editForm.name}
                        onChange={e => setEditForm({ ...editForm, name: e.target.value })} />
                      <select style={inp} value={editForm.position}
                        onChange={e => setEditForm({ ...editForm, position: e.target.value })}>
                        <option value="">— Select position —</option>
                        {positions.map(p => (
                          <option key={p._id} value={p.title}>{p.title}</option>
                        ))}
                      </select>
                      <input style={inp} type="number" value={editForm.order}
                        onChange={e => setEditForm({ ...editForm, order: e.target.value })} />
                      <label style={fileLabel}>
                        New photo: <input type="file" accept="image/*"
                          onChange={e => setEditForm({ ...editForm, newImage: e.target.files[0] })} />
                      </label>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button style={greenBtn} onClick={() => handleUpdateCandidate(c._id)} disabled={uploading}>Save</button>
                        <button style={ghostBtn} onClick={() => setEditingId(null)}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <img src={c.image_url} alt="" style={avatar} />
                        <div>
                          <b style={{ color: 'var(--text-color)' }}>{c.name}</b>
                          <br />
                          <small style={{ color: '#2ecc71' }}>{c.position}</small>
                          {c.application_id && (
                            <span style={badge}>via application</span>
                          )}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button style={editLink}
                          onClick={() => { setEditingId(c._id); setEditForm({ name: c.name, position: c.position, order: c.order || 0, newImage: null }); }}>
                          Edit
                        </button>
                        <button style={redLink} onClick={() => handleRemoveCandidateOverride(c._id)}>
                          Remove
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ══════════════ APPLICATIONS TAB ══════════════ */}
        {activeTab === 'applications' && (
          <div>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
              {['all','pending','approved','denied','removed'].map(f => (
                <button key={f} onClick={() => setAppFilter(f)}
                  style={{ ...ghostBtn, borderColor: appFilter === f ? '#2ecc71' : undefined, color: appFilter === f ? '#2ecc71' : undefined }}>
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                  {' '}({f === 'all' ? applications.length : applications.filter(a => a.status === f).length})
                </button>
              ))}
            </div>

            {appsLoading && <p style={{ opacity: 0.5 }}>Loading…</p>}

            {filteredApps.length === 0 && !appsLoading && (
              <p style={{ opacity: 0.5, textAlign: 'center', marginTop: '40px' }}>No applications in this category.</p>
            )}

            {filteredApps.map(app => (
              <div key={app._id} style={appCard}>
                <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
                  {app.image_url && (
                    <img src={app.image_url} alt="" style={{ ...avatar, width: '60px', height: '60px', flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                      <div>
                        <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>{app.full_name}</b>
                        <span style={{ ...statusBadge(app.status), marginLeft: '10px' }}>
                          {app.status.toUpperCase()}
                          {app.superadmin_override && ' (SA)'}
                        </span>
                      </div>
                      <small style={{ opacity: 0.5 }}>
                        {new Date(app.submitted_at).toLocaleDateString()}
                      </small>
                    </div>
                    <p style={{ margin: '4px 0', fontSize: '13px', color: '#2ecc71' }}>
                      Position: {app.position_title || app.position_id}
                    </p>
                    <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.6 }}>
                      ID: {app.student_id}
                    </p>
                    {app.manifesto && (
                      <p style={{ margin: '8px 0 0', fontSize: '13px', opacity: 0.8, lineHeight: '1.5' }}>
                        {app.manifesto}
                      </p>
                    )}
                    {app.votes && Object.keys(app.votes).length > 0 && (
                      <p style={{ margin: '6px 0 0', fontSize: '11px', opacity: 0.5 }}>
                        Commission votes: {Object.entries(app.votes).map(([k,v]) => `${k}: ${v}`).join(' · ')}
                      </p>
                    )}
                  </div>
                </div>

                {/* Superadmin action buttons — always available */}
                <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
                  {app.status !== 'approved' && app.status !== 'removed' && (
                    <button style={{ ...greenBtn, flex: 1 }} onClick={() => handleForceApprove(app._id)}>
                      ⚡ Force Approve
                    </button>
                  )}
                  {app.status !== 'denied' && app.status !== 'removed' && (
                    <button style={{ ...redBtn, flex: 1 }} onClick={() => handleForceDeny(app._id)}>
                      ✕ Force Deny
                    </button>
                  )}
                  {app.status === 'approved' && (
                    <button style={{ ...redBtn, flex: 1 }} onClick={() => {
                      if (window.confirm('Remove this approved candidate from the ballot?')) {
                        // Find matching candidate by application_id and remove
                        const cand = candidates.find(c => c.application_id === app._id);
                        if (cand) handleRemoveCandidateOverride(cand._id);
                        else alert('Candidate not found in ballot — may have been removed already.');
                      }
                    }}>
                      🗑️ Remove from Ballot
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ══════════════ COMMISSIONERS TAB ══════════════ */}
        {activeTab === 'commissioners' && (
          <div>
            <div style={{ ...card, marginBottom: '20px' }}>
              <h4 style={cardTitle}>Current Commissioners ({commissioners.length})</h4>
              {commissioners.length === 0 && (
                <p style={{ opacity: 0.5 }}>No commissioners assigned yet. Find voters below and toggle them.</p>
              )}
              {commissioners.map(c => (
                <div key={c.student_id} style={{ ...rowCard, marginBottom: '8px', flexWrap: 'wrap', gap: '10px' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <b style={{ color: 'var(--text-color)' }}>{c.full_name}</b>
                      {c.is_chief_commissioner && (
                        <span style={{ fontSize: '10px', backgroundColor: '#f1c40f20', color: '#f1c40f', padding: '2px 8px', borderRadius: '4px', fontWeight: 'bold' }}>
                          ⭐ Chief
                        </span>
                      )}
                      {c.is_finance_commissioner && (
                        <span style={{ fontSize: '10px', backgroundColor: '#2ecc7120', color: '#2ecc71', padding: '2px 8px', borderRadius: '4px', fontWeight: 'bold' }}>
                          💰 Finance
                        </span>
                      )}
                    </div>
                    <small style={{ opacity: 0.6 }}>{c.student_id}</small>
                    <br />
                    <small style={{ color: '#3498db' }}>Role: {c.commissioner_role || 'Commissioner'}</small>
                  </div>
              
                  <select
                    value={c.commissioner_role || 'Commissioner'}
                    onChange={e => handleSetRole(c.student_id, e.target.value)}
                    style={{ ...inp, width: 'auto', fontSize: '12px', padding: '6px 8px' }}
                  >
                    <option value="Chairperson EC">Chairperson EC</option>
                    <option value="Secretary EC">Secretary EC</option>
                    <option value="Commissioner">Commissioner</option>
                    <option value="Finance Commissioner">Finance Commissioner</option>
                    <option value="Deputy Finance">Deputy Finance</option>
                    <option value="Returning Officer">Returning Officer</option>
                  </select>
              
                  <div style={{ display: 'flex', gap: '8px' }}>
                    {c.is_chief_commissioner ? (
                      <button
                        onClick={() => handleClearChief(c.student_id)}
                        style={{ ...ghostBtn, color: '#f1c40f', borderColor: '#f1c40f', fontSize: '12px' }}>
                        Clear Chief
                      </button>
                    ) : (
                      <button
                        onClick={() => handleSetChief(c.student_id)}
                        style={{ ...ghostBtn, fontSize: '12px' }}>
                        ⭐ Set Chief
                      </button>
                    )}
                    {c.is_finance_commissioner ? (
                      <button
                        onClick={() => handleClearFinanceCommissioner(c.student_id)}
                        style={{ ...ghostBtn, color: '#2ecc71', borderColor: '#2ecc71', fontSize: '12px' }}>
                        Clear Finance
                      </button>
                    ) : (
                      <button
                        onClick={() => handleSetFinanceCommissioner(c.student_id)}
                        style={{ ...ghostBtn, fontSize: '12px' }}>
                        💰 Set Finance
                      </button>
                    )}
                    <button style={redLink} onClick={() => handleToggleCommissioner(c.student_id)}>
                      Revoke
                    </button>
                  </div>

                  {/* Credentials section */}
                  <div style={{ width: '100%', marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--border-color)' }}>
                    <small style={{ opacity: 0.5, fontSize: '11px' }}>
                      {c.commissioner_email
                        ? `📧 ${c.commissioner_email} — password set by commissioner ✓`
                        : '⚠️ No login credentials set yet'}
                    </small>
                    <div style={{ display: 'flex', gap: '8px', marginTop: '6px', flexWrap: 'wrap' }}>
                      <input
                        style={{ ...inp, flex: 1, fontSize: '12px', padding: '6px 8px' }}
                        placeholder="Email e.g. comm@example.com"
                        type="email"
                        value={commCredEmail[c.student_id] ?? c.commissioner_email ?? ''}
                        onChange={e => setCommCredEmail(prev => ({ ...prev, [c.student_id]: e.target.value }))}
                      />
                      <button
                        style={{ ...greenBtn, fontSize: '12px', padding: '6px 12px' }}
                        onClick={() => handleSetCommissionerCredentials(c.student_id)}
                      >
                        Send Credentials
                      </button>
                      {c.commissioner_email && (
                        <button
                          style={{ ...ghostBtn, fontSize: '12px', padding: '6px 12px' }}
                          disabled={resetting[c.student_id]}
                          onClick={() => handleResetCommissionerPassword(c.student_id)}
                        >
                          {resetting[c.student_id] ? 'Sending…' : '🔄 Reset Password'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            
            <h4 style={cardTitle}>Grant Commissioner Access</h4>
            <input style={{ ...inp, marginBottom: '12px' }}
              placeholder="Search voters by name or ID…"
              value={voterSearch}
              onChange={e => setVoterSearch(e.target.value)} />
            <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
              {filteredVoterList.filter(v => !commisssionerIds.has(v.student_id)).map(v => (
                <div key={v.student_id} style={rowCard}>
                  <div>
                    <b style={{ color: 'var(--text-color)' }}>{v.full_name}</b>
                    <br />
                    <small style={{ opacity: 0.6 }}>{v.student_id}</small>
                  </div>
                  <button style={greenBtn} onClick={() => handleToggleCommissioner(v.student_id)}>
                    + Make Commissioner
                  </button>
                </div>
              ))}
              {filteredVoterList.filter(v => !commisssionerIds.has(v.student_id)).length === 0 && (
                <p style={{ textAlign: 'center', opacity: 0.4, padding: '20px' }}>
                  {voterSearch ? 'No matching voters.' : 'All voters are already commissioners or no voters imported yet.'}
                </p>
              )}
            </div>
          </div>
        )}

        {/* ══════════════ VOTERS TAB ══════════════ */}
        {activeTab === 'voters' && (
          <div>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '16px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', width: '100%' }}>
                <div style={statCard}><small>Total Voters</small><h3>{electionVoters.length}</h3></div>
                <div style={statCard}><small>Voted</small><h3 style={{ color: '#2ecc71' }}>{electionVoters.filter(v => v.has_voted).length}</h3></div>
                <div style={statCard}><small>Turnout</small><h3>{turnout}%</h3></div>
                <div style={statCard}><small>Pending</small><h3 style={{ color: '#f1c40f' }}>{electionVoters.filter(v => !v.has_voted).length}</h3></div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', marginBottom: '14px', alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ ...card, flexDirection: 'row', alignItems: 'center', padding: '14px', gap: '12px', flex: 1 }}>
                <span style={{ fontSize: '13px', opacity: 0.7 }}>Import voters CSV</span>
                <input type="file" accept=".csv" onChange={handleImportVoters} disabled={importing} />
              </div>
              <button style={ghostBtn} onClick={fetchElectionData} disabled={loading}>
                {loading ? 'Syncing…' : '🔄 Refresh'}
              </button>
            </div>

            <input style={{ ...inp, marginBottom: '12px' }}
              placeholder="Search voters…"
              value={voterSearch2}
              onChange={e => setVoterSearch2(e.target.value)} />

            <div style={{ maxHeight: '500px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: '#1e293b' }}>
                  <tr>
                    {['ID','Name','Status'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredVoters.map(v => (
                    <tr key={v.student_id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={td}><code style={{ fontSize: '12px' }}>{v.student_id}</code></td>
                      <td style={td}>{v.full_name}</td>
                      <td style={td}>
                        <span style={{
                          fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
                          background: v.has_voted ? '#2ecc7120' : '#f1c40f20',
                          color: v.has_voted ? '#2ecc71' : '#f1c40f',
                        }}>
                          {v.has_voted ? 'VOTED' : (v.last_status || 'IDLE').toUpperCase()}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ══════════════ POSITIONS TAB ══════════════ */}
        {activeTab === 'positions' && (
          <div style={twoCol}>
            <div style={card}>
              <h4 style={cardTitle}>Add New Position</h4>
              <div style={formCol}>
                <input style={inp} placeholder="Position title (e.g. Guild President)"
                  value={newPosition.title}
                  onChange={e => setNewPosition({ ...newPosition, title: e.target.value })} />
                <input style={inp} placeholder="Description (optional)"
                  value={newPosition.description}
                  onChange={e => setNewPosition({ ...newPosition, description: e.target.value })} />
                <input style={inp} type="number" placeholder="Ballot order (0 = first)"
                  value={newPosition.order}
                  onChange={e => setNewPosition({ ...newPosition, order: parseInt(e.target.value) || 0 })} />
                <button style={greenBtn} onClick={handleAddPosition} disabled={posLoading}>
                  {posLoading ? 'Saving…' : '+ Add Position'}
                </button>
              </div>
            </div>
            <div>
              <h4 style={cardTitle}>Current Positions ({positions.length})</h4>
              {positions.length === 0 && (
                <p style={{ opacity: 0.5 }}>No positions yet. Add one to allow applicants to apply.</p>
              )}
              {positions.map(p => (
                <div key={p._id} style={rowCard}>
                  <div>
                    <b style={{ color: 'var(--text-color)' }}>{p.title}</b>
                    {p.description && <><br /><small style={{ opacity: 0.6 }}>{p.description}</small></>}
                    <br />
                    <small style={{ color: '#3498db' }}>Order: {p.order}</small>
                  </div>
                  <button style={redLink} onClick={() => handleDeletePosition(p._id)}>Delete</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ══════════════ BRANDING TAB ══════════════ */}
        {activeTab === 'branding' && (
          <div style={{ maxWidth: '500px' }}>
            <div style={card}>
              <h4 style={cardTitle}>Logo & Colour Scheme</h4>
              <div style={formCol}>
                <label style={{ fontSize: '12px', opacity: 0.7 }}>Organisation / Union Name</label>
                <input
                  style={inp}
                  placeholder="e.g. KYUCCU"
                  value={branding.org_name || ''}
                  onChange={e => setBranding({ ...branding, org_name: e.target.value })}
                />
        
                <label style={{ fontSize: '12px', opacity: 0.7 }}>Logo</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {/* Hidden file input */}
                  <input
                    type="file"
                    id="logo-upload"
                    accept="image/*"
                    style={{ display: 'none' }}
                    onChange={async e => {
                      const file = e.target.files[0];
                      if (!file) return;
                      try {
                        setBrandSaving(true);
                        const url = await uploadToCloudinary(file);
                        setBranding({ ...branding, logo_url: url });
                      } catch {
                        alert('Logo upload failed. Check Cloudinary env vars.');
                      } finally {
                        setBrandSaving(false);
                      }
                    }}
                  />
                  {/* Upload button */}
                  <label
                    htmlFor="logo-upload"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '9px 16px',
                      borderRadius: '8px',
                      border: '1.5px dashed rgba(255,255,255,0.3)',
                      cursor: brandSaving ? 'wait' : 'pointer',
                      fontSize: '13px',
                      fontWeight: '500',
                      color: 'inherit',
                      transition: 'border-color 0.2s',
                      width: 'fit-content',
                      opacity: brandSaving ? 0.5 : 1,
                    }}
                  >
                    {brandSaving ? '⏳ Uploading…' : '📁 Choose logo image'}
                  </label>
                          
                  {/* Preview or placeholder */}
                  {branding.logo_url ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <img
                        src={branding.logo_url}
                        alt="Logo preview"
                        style={{ height: '72px', objectFit: 'contain', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', padding: '4px' }}
                      />
                      <button
                        onClick={() => setBranding({ ...branding, logo_url: '' })}
                        style={{
                          background: 'rgba(255,80,80,0.15)',
                          border: 'none',
                          borderRadius: '6px',
                          padding: '5px 10px',
                          cursor: 'pointer',
                          fontSize: '12px',
                          color: '#ff6b6b',
                        }}
                      >
                        ✕ Remove
                      </button>
                    </div>
                  ) : (
                    <div style={{
                      height: '72px', borderRadius: '8px',
                      background: 'rgba(255,255,255,0.04)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '12px', opacity: 0.4,
                    }}>
                      No logo selected
                    </div>
                  )}
                </div>
        
                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>Primary colour</label>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <input type="color" value={branding.primary_color}
                    onChange={e => setBranding({ ...branding, primary_color: e.target.value })}
                    style={{ width: '48px', height: '40px', border: 'none', cursor: 'pointer', borderRadius: '6px' }} />
                  <input style={{ ...inp, flex: 1 }} value={branding.primary_color}
                    onChange={e => setBranding({ ...branding, primary_color: e.target.value })} />
                </div>
        
                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>Accent colour</label>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <input type="color" value={branding.accent_color}
                    onChange={e => setBranding({ ...branding, accent_color: e.target.value })}
                    style={{ width: '48px', height: '40px', border: 'none', cursor: 'pointer', borderRadius: '6px' }} />
                  <input style={{ ...inp, flex: 1 }} value={branding.accent_color}
                    onChange={e => setBranding({ ...branding, accent_color: e.target.value })} />
                </div>
        
                {/* Live preview strip */}
                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>University / Institution Name</label>
                <input
                  style={inp}
                  placeholder="e.g. Kyambogo University"
                  value={branding.university_name || ''}
                  onChange={e => setBranding({ ...branding, university_name: e.target.value })}
                />

                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>University Logo</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <input
                    type="file"
                    id="university-logo-upload"
                    accept="image/*"
                    style={{ display: 'none' }}
                    onChange={async e => {
                      const file = e.target.files[0];
                      if (!file) return;
                      try {
                        setBrandSaving(true);
                        const url = await uploadToCloudinary(file);
                        setBranding({ ...branding, university_logo_url: url });
                      } catch {
                        alert('University logo upload failed. Check Cloudinary env vars.');
                      } finally {
                        setBrandSaving(false);
                      }
                    }}
                  />
                  <label
                    htmlFor="university-logo-upload"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '9px 16px',
                      borderRadius: '8px',
                      border: '1.5px dashed rgba(255,255,255,0.3)',
                      cursor: brandSaving ? 'wait' : 'pointer',
                      fontSize: '13px',
                      fontWeight: '500',
                      color: 'inherit',
                      width: 'fit-content',
                      opacity: brandSaving ? 0.5 : 1,
                    }}
                  >
                    {brandSaving ? '⏳ Uploading…' : '📁 Choose university logo'}
                  </label>

                  {branding.university_logo_url ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <img
                        src={branding.university_logo_url}
                        alt="University logo preview"
                        style={{ height: '72px', objectFit: 'contain', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', padding: '4px' }}
                      />
                      <button
                        onClick={() => setBranding({ ...branding, university_logo_url: '' })}
                        style={{
                          background: 'rgba(255,80,80,0.15)',
                          border: 'none',
                          borderRadius: '6px',
                          padding: '5px 10px',
                          cursor: 'pointer',
                          fontSize: '12px',
                          color: '#ff6b6b',
                        }}
                      >
                        ✕ Remove
                      </button>
                    </div>
                  ) : (
                    <div style={{
                      height: '72px', borderRadius: '8px',
                      background: 'rgba(255,255,255,0.04)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '12px', opacity: 0.4,
                    }}>
                      No university logo selected
                    </div>
                  )}
                </div>

                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>WhatsApp Support Number (digits only, with country code)</label>
                <input
                  style={inp}
                  placeholder="e.g. 256745707723"
                  value={branding.support_phone || ''}
                  onChange={e => setBranding({ ...branding, support_phone: e.target.value })}
                />

                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>Election Details PDF URL</label>
                <input
                  style={inp}
                  placeholder="e.g. https://your-bucket.r2.dev/election-details.pdf"
                  value={branding.support_pdf_url || ''}
                  onChange={e => setBranding({ ...branding, support_pdf_url: e.target.value })}
                />

                <label style={{ fontSize: '12px', opacity: 0.7, marginTop: '10px' }}>Cc List (one per line)</label>
                <textarea
                  placeholder={`e.g.\n${branding.org_name || 'Organisation'} Patron\n${branding.org_name || 'Organisation'} President\nDean of Students`}
                  value={(branding.cc_list || []).join('\n')}
                  onChange={e => setBranding({
                    ...branding,
                    cc_list: e.target.value.split('\n').map(l => l.trim()).filter(Boolean)
                  })}
                  rows={5}
                  style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }}
                />
                <small style={{ color: '#64748b', fontSize: '11px' }}>
                  {(branding.cc_list || []).length} entries — these appear at the bottom of the official printed report
                </small>
                <div style={{
                  marginTop: '14px', padding: '12px 16px', borderRadius: '8px',
                  backgroundColor: branding.primary_color, display: 'flex', gap: '10px', alignItems: 'center'
                }}>
                  <span style={{ color: '#fff', fontWeight: 'bold', fontSize: '13px' }}>Preview nav bar</span>
                  <span style={{
                    backgroundColor: branding.accent_color, color: branding.primary_color,
                    padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold'
                  }}>Active button</span>
                </div>
        
                <button style={{ ...greenBtn, marginTop: '14px' }} onClick={handleSaveBranding} disabled={brandSaving}>
                  {brandSaving ? 'Saving…' : '💾 Save Branding'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ══════════════ ELECTION TAB ══════════════ */}
        {activeTab === 'election' && (
          <div style={{ maxWidth: '600px' }}>
            <div style={card}>
              <h4 style={cardTitle}>Schedule Election Period</h4>
              <div style={formCol}>
                <label style={{ fontSize: '12px', opacity: 0.7 }}>Start time</label>
                <input type="datetime-local" style={inp} value={startTime}
                  onChange={e => setStartTime(e.target.value)} />
                <label style={{ fontSize: '12px', opacity: 0.7 }}>End time</label>
                <input type="datetime-local" style={inp} value={endTime}
                  onChange={e => setEndTime(e.target.value)} />
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button style={greenBtn} onClick={handleScheduleTimer}>
                    {timerActive ? '🔄 Update Schedule' : 'Set Schedule'}
                  </button>
                  {timerActive && (
                    <button style={ghostBtn} onClick={handleClearSchedule}>Clear Schedule</button>
                  )}
                </div>
                {timerActive && (
                  <p style={{ color: '#2ecc71', fontSize: '12px', margin: '4px 0 0' }}>
                    Active: {new Date(startTime).toLocaleString()} — {new Date(endTime).toLocaleString()}
                  </p>
                )}
              </div>
            </div>

            <div style={{ ...card, marginTop: '16px', borderColor: '#e74c3c' }}>
              <h4 style={{ ...cardTitle, color: '#e74c3c' }}>🧨 Danger Zone</h4>
              <p style={{ fontSize: '13px', opacity: 0.7, margin: '0 0 12px' }}>
                Full election reset — deletes ALL votes permanently. Certified elections cannot be reset.
              </p>
              <button
                onClick={handleResetElection}
                disabled={isCertified}
                style={{
                  ...btn, backgroundColor: '#d63031',
                  opacity: isCertified ? 0.4 : 1,
                  cursor: isCertified ? 'not-allowed' : 'pointer',
                }}
              >
                {isCertified ? 'Cannot Reset — Results Certified' : 'Full Election Reset'}
              </button>
            </div>
          </div>
        )}
        
        {/* ══════════════ IT ADMINS TAB ══════════════ */}
        {activeTab === 'it_admins' && (
          <div style={twoCol}>
            <div style={card}>
              <h4 style={cardTitle}>Current IT Admins ({itAdmins.length})</h4>
              {itAdmins.length === 0 && (
                <p style={{ opacity: 0.5 }}>No IT admins assigned yet. Find voters below and toggle them.</p>
              )}
              {itAdmins.map(a => (
                <div key={a.student_id} style={{ ...rowCard, flexDirection: 'column', alignItems: 'stretch', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <b style={{ color: 'var(--text-color)' }}>{a.full_name}</b>
                      <br />
                      <small style={{ opacity: 0.6 }}>{a.student_id}</small>
                      {a.it_admin_email && (
                        <>
                          <br />
                          <small style={{ color: '#3498db' }}>{a.it_admin_email}</small>
                        </>
                      )}
                    </div>
                    <button style={redLink} onClick={() => handleToggleItAdmin(a.student_id)}>
                      Revoke
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <input
                      style={{ ...inp, flex: 1, minWidth: '180px' }}
                      placeholder="Email"
                      value={itCredEmail[a.student_id] || ''}
                      onChange={e => setItCredEmail(prev => ({ ...prev, [a.student_id]: e.target.value }))}
                    />
                    <button style={greenBtn} onClick={() => handleSetItAdminCredentials(a.student_id)}>
                      Send Credentials
                    </button>
                    {a.it_admin_email && (
                      <button
                        style={ghostBtn}
                        disabled={resetting[a.student_id]}
                        onClick={() => handleResetItAdminPassword(a.student_id)}
                      >
                        {resetting[a.student_id] ? 'Sending…' : '🔄 Reset Password'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div>
              <h4 style={{ ...cardTitle, marginBottom: '5px' }}>Grant IT Admin Access</h4>
              <input style={{ ...inp, marginBottom: '12px' }}
                placeholder="Search voters by name or ID…"
                value={itAdminSearch}
                onChange={e => setItAdminSearch(e.target.value)} />
              <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
                {voters
                  .filter(v => !itAdmins.some(a => a.student_id === v.student_id))
                  .filter(v =>
                    v.full_name?.toLowerCase().includes(itAdminSearch.toLowerCase()) ||
                    v.student_id?.toLowerCase().includes(itAdminSearch.toLowerCase())
                  )
                  .map(v => (
                    <div key={v.student_id} style={rowCard}>
                      <div>
                        <b style={{ color: 'var(--text-color)' }}>{v.full_name}</b>
                        <br />
                        <small style={{ opacity: 0.6 }}>{v.student_id}</small>
                      </div>
                      <button style={greenBtn} onClick={() => handleToggleItAdmin(v.student_id)}>
                        + Make IT Admin
                      </button>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}

        {/* ══════════════ STUDENT CHANGES TAB (superadmin view) ══════════════ */}
        {activeTab === 'student_changes' && (
          <div>
            <div style={twoCol}>
              <div style={card}>
                <h4 style={cardTitle}>Add Student Directly</h4>
                <form onSubmit={handleSuperAdminAddStudent} style={formCol}>
                  <input style={inp} placeholder="Student ID" value={saDirectAdd.student_id}
                    onChange={e => setSaDirectAdd({ ...saDirectAdd, student_id: e.target.value })} required />
                  <input style={inp} placeholder="Full name" value={saDirectAdd.full_name}
                    onChange={e => setSaDirectAdd({ ...saDirectAdd, full_name: e.target.value })} required />
                  <input style={inp} placeholder="Phone" value={saDirectAdd.phone}
                    onChange={e => setSaDirectAdd({ ...saDirectAdd, phone: e.target.value })} required />
                  <input style={inp} placeholder="Reason" value={saDirectAdd.reason}
                    onChange={e => setSaDirectAdd({ ...saDirectAdd, reason: e.target.value })} required />
                  <button type="submit" style={greenBtn}>+ Add Student Instantly</button>
                </form>
              </div>

              <div style={card}>
                <h4 style={cardTitle}>Remove Student Directly</h4>
                <div style={formCol}>
                  <div style={{ position: 'relative' }}>
                    <input
                      style={inp}
                      placeholder="Search by name or student ID…"
                      value={removeSearch}
                      onChange={e => {
                        setRemoveSearch(e.target.value);
                        setSaDirectRemove({ ...saDirectRemove, student_id: '' });
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
                                setSaDirectRemove({ ...saDirectRemove, student_id: v.student_id });
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
                  {saDirectRemove.student_id && (
                    <p style={{ fontSize: '11px', color: '#2ecc71', margin: '2px 0 0' }}>
                      ✓ Selected: {saDirectRemove.student_id}
                    </p>
                  )}
                  <input style={inp} placeholder="Reason" value={saDirectRemove.reason}
                    onChange={e => setSaDirectRemove({ ...saDirectRemove, reason: e.target.value })} />
                  <button style={redBtn} onClick={handleSuperAdminRemoveStudent}>
                    🗑️ Remove Student Instantly
                  </button>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '8px', margin: '20px 0 16px', flexWrap: 'wrap' }}>
              {['all', 'pending', 'approved', 'force_approved', 'denied', 'force_denied', 'cancelled'].map(f => (
                <button key={f} onClick={() => setScFilter(f)}
                  style={{ ...ghostBtn, borderColor: scFilter === f ? '#2ecc71' : undefined, color: scFilter === f ? '#2ecc71' : undefined }}>
                  {f.replace('_', ' ')}
                  {' '}({f === 'all' ? studentChanges.length : studentChanges.filter(c => c.status === f).length})
                </button>
              ))}
            </div>

            {(scFilter === 'all' ? studentChanges : studentChanges.filter(c => c.status === scFilter)).map(change => (
              <div key={change._id} style={appCard}>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <b style={{ color: 'var(--text-color)' }}>
                      {change.change_type === 'add' ? '➕ Add' : '➖ Remove'}
                    </b>
                    <span style={{ ...statusBadge(change.status), marginLeft: '10px' }}>
                      {change.status.toUpperCase().replace('_', ' ')}
                    </span>
                  </div>
                  <small style={{ opacity: 0.45 }}>
                    {new Date(change.requested_at).toLocaleDateString()}
                  </small>
                </div>
                <p style={{ margin: '8px 0 2px', fontSize: '13px', color: 'var(--text-color)' }}>
                  <b>{change.full_name}</b> — <code style={{ fontSize: '12px' }}>{change.student_id}</code>
                </p>
                <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.6 }}>
                  Reason: {change.reason}
                </p>
                <p style={{ margin: '2px 0', fontSize: '11px', opacity: 0.5 }}>
                  Requested by: {change.requested_by}
                </p>
                
                {change.payment_method && (
                  <div style={{ marginTop: '8px', padding: '8px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                    <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                      Payment: <strong style={{ color: 'var(--text-color)' }}>{change.payment_method}</strong>
                    </p>
                    {change.payment_proof_url && (
                      <a href={change.payment_proof_url} target="_blank" rel="noopener noreferrer"
                        style={{ fontSize: '12px', color: '#3498db', textDecoration: 'none' }}>
                        🧾 View Receipt
                      </a>
                    )}
                  </div>
                )}

                {change.status === 'pending' && (
                  <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                    <button style={{ ...greenBtn, flex: 1 }} onClick={() => handleForceStudentChange(change._id, 'approve')}>
                      ⚡ Force Approve
                    </button>
                    <button style={{ ...redBtn, flex: 1 }} onClick={() => handleForceStudentChange(change._id, 'deny')}>
                      ✕ Force Deny
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ══════════════ FINANCIAL CONTROLLERS TAB ══════════════ */}
        {activeTab === 'financial_controllers' && (
          <div style={twoCol}>
            <div style={card}>
              <h4 style={cardTitle}>Current Financial Controllers ({financialControllers.length})</h4>
              {financialControllers.length === 0 && (
                <p style={{ opacity: 0.5 }}>No Financial Controllers assigned yet. Find voters below and toggle them.</p>
              )}
              {financialControllers.map(a => (
                <div key={a.student_id} style={{ ...rowCard, flexDirection: 'column', alignItems: 'stretch', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <b style={{ color: 'var(--text-color)' }}>{a.full_name}</b>
                      <br />
                      <small style={{ opacity: 0.6 }}>{a.student_id}</small>
                      {a.financial_controller_email && (
                        <>
                          <br />
                          <small style={{ color: '#3498db' }}>{a.financial_controller_email}</small>
                        </>
                      )}
                    </div>
                    <button style={redLink} onClick={() => handleToggleFinancialController(a.student_id)}>
                      Revoke
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <input
                      style={{ ...inp, flex: 1, minWidth: '180px' }}
                      placeholder="Email"
                      value={fcCredEmail[a.student_id] || ''}
                      onChange={e => setFcCredEmail(prev => ({ ...prev, [a.student_id]: e.target.value }))}
                    />
                    <button style={greenBtn} onClick={() => handleSetFinancialControllerCredentials(a.student_id)}>
                      Send Credentials
                    </button>
                    {a.financial_controller_email && (
                      <button
                        style={ghostBtn}
                        disabled={resetting[a.student_id]}
                        onClick={() => handleResetFinancialControllerPassword(a.student_id)}
                      >
                        {resetting[a.student_id] ? 'Sending…' : '🔄 Reset Password'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div>
              <h4 style={{ ...cardTitle, marginBottom: '5px' }}>Grant Financial Controller Access</h4>
              <input style={{ ...inp, marginBottom: '12px' }}
                placeholder="Search voters by name or ID…"
                value={fcSearch}
                onChange={e => setFcSearch(e.target.value)} />
              <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
                {voters
                  .filter(v => !financialControllers.some(a => a.student_id === v.student_id))
                  .filter(v =>
                    v.full_name?.toLowerCase().includes(fcSearch.toLowerCase()) ||
                    v.student_id?.toLowerCase().includes(fcSearch.toLowerCase())
                  )
                  .map(v => (
                    <div key={v.student_id} style={rowCard}>
                      <div>
                        <b style={{ color: 'var(--text-color)' }}>{v.full_name}</b>
                        <br />
                        <small style={{ opacity: 0.6 }}>{v.student_id}</small>
                      </div>
                      <button style={greenBtn} onClick={() => handleToggleFinancialController(v.student_id)}>
                        + Make Financial Controller
                      </button>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}

        {/* ══════════════ OVERSEERS TAB ══════════════ */}
        {activeTab === 'overseers' && (
          <div style={twoCol}>
            <div style={card}>
              <h4 style={cardTitle}>Current Overseers ({overseers.length})</h4>
              {overseers.length === 0 && (
                <p style={{ opacity: 0.5 }}>No Overseers assigned yet. Find voters below and toggle them.</p>
              )}
              {overseers.map(a => (
                <div key={a.student_id} style={{ ...rowCard, flexDirection: 'column', alignItems: 'stretch', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <b style={{ color: 'var(--text-color)' }}>{a.full_name}</b>
                      <br />
                      <small style={{ opacity: 0.6 }}>{a.student_id}</small>
                      {a.overseer_email && (
                        <>
                          <br />
                          <small style={{ color: '#3498db' }}>{a.overseer_email}</small>
                        </>
                      )}
                    </div>
                    <button style={redLink} onClick={() => handleToggleOverseer(a.student_id)}>
                      Revoke
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <input
                      style={{ ...inp, flex: 1, minWidth: '180px' }}
                      placeholder="Email"
                      value={ovCredEmail[a.student_id] || ''}
                      onChange={e => setOvCredEmail(prev => ({ ...prev, [a.student_id]: e.target.value }))}
                    />
                    <button style={greenBtn} onClick={() => handleSetOverseerCredentials(a.student_id)}>
                      Send Credentials
                    </button>
                    {a.overseer_email && (
                      <button
                        style={ghostBtn}
                        disabled={resetting[a.student_id]}
                        onClick={() => handleResetOverseerPassword(a.student_id)}
                      >
                        {resetting[a.student_id] ? 'Sending…' : '🔄 Reset Password'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div>
              <h4 style={{ ...cardTitle, marginBottom: '5px' }}>Grant Overseer Access</h4>
              <input style={{ ...inp, marginBottom: '12px' }}
                placeholder="Search voters by name or ID…"
                value={ovSearch}
                onChange={e => setOvSearch(e.target.value)} />
              <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
                {voters
                  .filter(v => !overseers.some(a => a.student_id === v.student_id))
                  .filter(v =>
                    v.full_name?.toLowerCase().includes(ovSearch.toLowerCase()) ||
                    v.student_id?.toLowerCase().includes(ovSearch.toLowerCase())
                  )
                  .map(v => (
                    <div key={v.student_id} style={rowCard}>
                      <div>
                        <b style={{ color: 'var(--text-color)' }}>{v.full_name}</b>
                        <br />
                        <small style={{ opacity: 0.6 }}>{v.student_id}</small>
                      </div>
                      <button style={greenBtn} onClick={() => handleToggleOverseer(v.student_id)}>
                        + Make Overseer
                      </button>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}

        {/* ══════════════ ORGANIZATIONS TAB (multi-tenancy) ══════════════ */}
        {activeTab === 'organizations' && (
          <div>
            <div style={{ ...card, marginBottom: '20px', maxWidth: '480px' }}>
              <h4 style={cardTitle}>Provision New Organization</h4>
              <form onSubmit={handleCreateOrg} style={formCol}>
                <input
                  style={inp}
                  placeholder="Organization name (e.g. KYUCCU)"
                  value={orgForm.name}
                  onChange={e => setOrgForm(prev => ({ ...prev, name: e.target.value }))}
                />
                <input
                  style={inp}
                  placeholder="Slug (optional — auto-generated if blank)"
                  value={orgForm.slug}
                  onChange={e => setOrgForm(prev => ({ ...prev, slug: e.target.value }))}
                />
                <button type="submit" style={greenBtn} disabled={orgCreating}>
                  {orgCreating ? 'Provisioning…' : '+ Create Organization'}
                </button>
              </form>
              <p style={{ margin: '10px 0 0', fontSize: '12px', opacity: 0.55 }}>
                The returned slug is what gets set as <code>VITE_ORG_SLUG</code> in that org's frontend deployment.
              </p>
            </div>

            <div style={card}>
              <h4 style={cardTitle}>Provisioned Organizations ({organizations.length})</h4>
              {organizations.length === 0 && (
                <p style={{ opacity: 0.5 }}>No organizations provisioned yet.</p>
              )}
              {organizations.map(o => (
                <div key={o._id} style={rowCard}>
                  <div>
                    <b style={{ color: 'var(--text-color)' }}>{o.name}</b>
                    <br />
                    <small style={{ opacity: 0.6 }}>slug: <code>{o.slug}</code></small>
                  </div>
                  <small style={{ opacity: 0.45 }}>
                    {new Date(o.created_at).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' })}
                  </small>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ══════════════ AUDIT LOG TAB ══════════════ */}
        {activeTab === 'audit_log' && (
          <div>
            <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
              <input
                style={{ ...inp, maxWidth: '300px' }}
                placeholder="Filter by action e.g. 'application'"
                value={auditFilter}
                onChange={e => setAuditFilter(e.target.value)}
              />
              <button style={ghostBtn} onClick={fetchAuditLog}>🔍 Filter</button>
              {auditFilter && (
                <button style={ghostBtn} onClick={() => { setAuditFilter(''); fetchAuditLog(); }}>Clear</button>
              )}
            </div>

            {auditLoading && <p style={{ opacity: 0.5 }}>Loading…</p>}

            <div style={{ maxHeight: '600px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead style={{ position: 'sticky', top: 0, backgroundColor: '#1e293b' }}>
                  <tr>
                    {['Timestamp', 'Action', 'Actor', 'Details'].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {auditLog.map(entry => (
                    <tr key={entry._id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ ...td, whiteSpace: 'nowrap', fontSize: '11px', opacity: 0.7 }}>
                        {new Date(entry.timestamp).toLocaleString('en-UG', { dateStyle: 'short', timeStyle: 'short' })}
                      </td>
                      <td style={{ ...td, fontWeight: '600' }}>{entry.action.replace(/_/g, ' ')}</td>
                      <td style={{ ...td, fontSize: '12px' }}>{entry.actor}</td>
                      <td style={{ ...td, fontSize: '11px', opacity: 0.7 }}>
                        {Object.entries(entry.details || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                      </td>
                    </tr>
                  ))}
                  {auditLog.length === 0 && !auditLoading && (
                    <tr>
                      <td colSpan={4} style={{ ...td, textAlign: 'center', opacity: 0.4, padding: '30px' }}>
                        No log entries found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Status badge helper ──
function statusBadge(status) {
  const map = {
    pending:  { background: '#f1c40f20', color: '#f1c40f' },
    approved: { background: '#2ecc7120', color: '#2ecc71' },
    denied:   { background: '#e74c3c20', color: '#e74c3c' },
    removed:  { background: '#95a5a620', color: '#95a5a6' },
  };
  return {
    fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
    ...(map[status] || { background: '#ffffff20', color: '#fff' }),
  };
}

// ── Styles ──
const dropdownList = { position: 'absolute', top: '100%', left: 0, right: 0, backgroundColor: 'var(--card-bg)', border: '1px solid var(--border-color)', borderRadius: '8px', marginTop: '4px', maxHeight: '220px', overflowY: 'auto', zIndex: 20 };
const dropdownItem = { padding: '10px 12px', fontSize: '13px', color: 'var(--text-color)', cursor: 'pointer', borderBottom: '1px solid var(--border-color)' };
const outerWrap   = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container   = { width: '95%', maxWidth: '1200px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const headerFlex  = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' };
const tabBar      = { display: 'flex', gap: '4px', marginBottom: '24px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap' };
const tab         = { background: 'none', border: 'none', padding: '10px 16px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px', whiteSpace: 'nowrap' };
const twoCol      = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' };
const card        = { padding: '20px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--bg-color)' };
const cardTitle   = { margin: '0 0 14px', color: 'var(--text-color)', fontSize: '15px', fontWeight: '600' };
const rowCard     = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 14px', borderBottom: '1px solid var(--border-color)', gap: '10px' };
const appCard     = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
const formCol     = { display: 'flex', flexDirection: 'column', gap: '10px' };
const inp         = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const fileLabel   = { fontSize: '12px', opacity: 0.7 };
const btn         = { padding: '10px 18px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const greenBtn    = { ...btn, backgroundColor: '#2ecc71' };
const redBtn      = { ...btn, backgroundColor: '#e74c3c' };
const ghostBtn    = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const editLink    = { background: 'none', border: 'none', color: '#3498db', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const redLink     = { background: 'none', border: 'none', color: '#e74c3c', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const badge       = { marginLeft: '8px', fontSize: '10px', backgroundColor: '#3498db20', color: '#3498db', padding: '2px 6px', borderRadius: '4px' };
const avatar      = { width: '44px', height: '44px', borderRadius: '6px', objectFit: 'cover' };
const statCard    = { padding: '14px', border: '1px solid var(--border-color)', borderRadius: '10px', textAlign: 'center', color: 'var(--text-color)' };
const th          = { padding: '10px 14px', textAlign: 'left', color: '#fff', fontSize: '11px', textTransform: 'uppercase' };
const td          = { padding: '10px 14px', color: 'var(--text-color)', fontSize: '13px' };
