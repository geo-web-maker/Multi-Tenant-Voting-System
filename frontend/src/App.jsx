import React, { useState, useEffect } from 'react'; 
import api, { API_BASE, ADMIN_TOKEN_KEY } from './api';
import OtpInput from './components/OtpInput';
import BallotBox from './components/BallotBox';
import Results from './components/Results';
import AdminDashboard from './components/AdminDashboard';
import SuperAdminDashboard from './components/SuperAdminDashboard';
import CommissionDashboard from './components/CommissionDashboard';
import ApplicantPortal from './components/ApplicantPortal';
import ITAdminDashboard from './components/ITAdminDashboard';
import FinancialControllerDashboard from './components/FinancialControllerDashboard';
import OverseerDashboard from './components/OverseerDashboard';

function App() {
  const [supportPdfUrl, setSupportPdfUrl] = useState("");
  const [supportPhone, setSupportPhone] = useState("");
  const [showGuide, setShowGuide] = useState(false); // New state for Guide
  const [candidates, setCandidates] = useState([]); // To store candidates for preview
  const [step, setStep] = useState(1); 
  const [view, setView] = useState("voter"); 
  const [studentId, setStudentId] = useState("");
  const [name, setName] = useState("");
  const [otp, setOtp] = useState("");
  const [placeholderText, setPlaceholderText] = useState({ id: "", name: "" });
  const [isDeleting, setIsDeleting] = useState(false);
  const [loopNum, setLoopNum] = useState(0);
  const [typingSpeed, setTypingSpeed] = useState(150);
  const [isAdminPath, setIsAdminPath] = useState(false);
  const [isElectionOpen, setIsElectionOpen] = useState(true);
  const [maskedNumbers, setMaskedNumbers] = useState([]);
  const [orgName, setOrgName] = useState("");
  const [timer, setTimer] = useState(0);
  const [selectedPhone, setSelectedPhone] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);
  const [statusModal, setStatusModal] = useState({ 
    show: false, 
    title: '', 
    message: '', 
    type: 'success' 
  });
  const examples = [
    { id: "23/U/BCS/10245/GV", name: "Ayebale Elizabeth" },
    { id: "22/U/ISD/08940/PD", name: "Namusoke Dorothy Nalwadda" },
    { id: "23/U/AGE/11223/GV", name: "Kaggwa Paul" },
    { id: "21/U/BSE/44556/PE", name: "Sserwadda Valentino" },
    { id: "23/U/BPH/00341/GV", name: "Bakanansa Jesca" }
  ];
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [pendingAdminEmail, setPendingAdminEmail]     = useState('');
  const [newPasswordForm, setNewPasswordForm]         = useState({ old_password: '', new_password: '', confirm_password: '' });
  const [passwordChangeError, setPasswordChangeError] = useState('');
  const [passwordChangeSubmitting, setPasswordChangeSubmitting] = useState(false);
  const [logoUrl, setLogoUrl] = useState("");
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('theme');
    if (saved === 'light' || saved === 'dark') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  
// --- USEEFFECTS ---
useEffect(() => {
  api.get('/superadmin/branding').then(res => {
    if (res.data.logo_url) {
      setLogoUrl(res.data.logo_url);
    if (res.data.support_pdf_url) 
      setSupportPdfUrl(res.data.support_pdf_url);
    if (res.data.support_phone) 
      setSupportPhone(res.data.support_phone);
    
      // Update browser tab favicon dynamically
      const favicon = document.querySelector("link[rel='icon']");
      if (favicon) favicon.href = res.data.logo_url;
    }
    if (res.data.primary_color)
      document.documentElement.style.setProperty('--brand-primary', res.data.primary_color);
    if (res.data.accent_color)
      document.documentElement.style.setProperty('--brand-accent', res.data.accent_color);
    if (res.data.org_name) 
      setOrgName(res.data.org_name);

    // Update browser tab title dynamically
    if (res.data.org_name) document.title = `${res.data.org_name} Election Portal`;
  }).catch(() => {});
}, []);
  
  useEffect(() => {
    // Stop the animation if the user has already started typing
    if (studentId !== "" || name !== "") return;
  
    const handleTyping = () => {
      const i = loopNum % examples.length;
      const fullId = examples[i].id;
      const fullName = examples[i].name;
  
      // 1. Calculate the next step for both strings
      const nextId = isDeleting 
        ? fullId.substring(0, placeholderText.id.length - 1) 
        : fullId.substring(0, placeholderText.id.length + 1);

      const nextName = isDeleting 
        ? fullName.substring(0, placeholderText.name.length - 1) 
        : fullName.substring(0, placeholderText.name.length + 1);

      setPlaceholderText({ id: nextId, name: nextName });
  
      // 2. Determine if the ENTIRE sequence is done
      const finishedTyping = !isDeleting && nextId === fullId && nextName === fullName;
      const finishedErasing = isDeleting && nextId === "" && nextName === "";

      // 3. Speed Logic (Fixes the 'nextSpeed' declaration error)
      let speed = isDeleting ? 40 : 120; 
  
      if (finishedTyping) {
        // Hold the full text for 2 seconds so students can read it
        speed = 2000;
        setIsDeleting(true);
      } else if (finishedErasing) {
        // Move to the next person in the list
        setIsDeleting(false);
        setLoopNum(loopNum + 1);
        speed = 500;
      }
  
      setTypingSpeed(speed);
    };
  
    const timer = setTimeout(handleTyping, typingSpeed);
    return () => clearTimeout(timer);

  }, [placeholderText, isDeleting, loopNum, typingSpeed, studentId, name, examples]);
  
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await api.get('/election-status');
        setIsElectionOpen(res.data.is_open);
      } catch (err) {
        console.error("Could not fetch election status");
      }
    };
    checkStatus();
  }, []);

  useEffect(() => {
    let interval = null;
    if (timer > 0) {
      interval = setInterval(() => {
        setTimer((prev) => prev - 1);
      }, 1000);
    } else {
      clearInterval(interval);
    }
    return () => clearInterval(interval);
  }, [timer]);

    useEffect(() => {
      const fetchCandidates = async () => {
        try {
          const res = await api.get('/candidates');
          setCandidates(res.data);
        } catch (err) {
          console.error("Error fetching candidates for guide", err);
        }
      };
      fetchCandidates();
    }, []);

  // --- HANDLERS ---
  const handleVoteSuccess = () => {
    // 1. Create the cookie
    const expiry = new Date();
    expiry.setSeconds(expiry.getSeconds() + 86400); 
    
    // 2. Save it to the browser
    document.cookie = `voted_status=true; expires=${expiry.toUTCString()}; path=/; SameSite=Lax`;

    // 3. Move to the final screen
    setStep(4);
  };

  const checkDeviceLock = () => {
    const hasVoted = document.cookie.split('; ').find(row => row.startsWith('voted_status='));
    if (hasVoted) {
      setStatusModal({
        show: true,
        title: "Device Locked",
        message: "This device has already been used to cast a vote.",
        type: "error"
      });
      return true;
    }
    return false;
  };
  
const handleVerifyIdentity = async (selectedIdx = null) => {
      setIsVerifying(true);
      try {
        const endpoint = isAdminPath ? "/verify-admin" : "/verify-identity";
      
        const payload = isAdminPath
          ? { email: studentId, password: name }
          : { student_id: studentId, full_name: name, phone_index: selectedIdx };
    
        const res = await api.post(endpoint, payload);
  
        if (res.data.bypass === true) {
          sessionStorage.setItem("admin_role", res.data.role);
          if (res.data.access_token) {
            sessionStorage.setItem(ADMIN_TOKEN_KEY, res.data.access_token);
          }
          if (res.data.commissioner_id) {
            sessionStorage.setItem("commissioner_id", res.data.commissioner_id);
          }
          if (res.data.it_admin_id) {
            sessionStorage.setItem("it_admin_id",   res.data.it_admin_id);
            sessionStorage.setItem("it_admin_name", res.data.full_name || "");
          }
          if (res.data.financial_controller_id) {
            sessionStorage.setItem("financial_controller_id", res.data.financial_controller_id);
            sessionStorage.setItem("financial_controller_name", res.data.full_name || "");
          }
          if (res.data.overseer_id) {
            sessionStorage.setItem("overseer_id", res.data.overseer_id);
            sessionStorage.setItem("overseer_name", res.data.full_name || "");
          }
        
          if (res.data.role !== "superadmin" && res.data.must_change_password) {
            setPendingAdminEmail(studentId);
            setMustChangePassword(true);
            return;
          }
        
          setView(res.data.role);
          return;
        }
        sessionStorage.setItem("admin_role",res.data.role || "commission");
  
        if (res.data.status === "needs_selection") {
          setMaskedNumbers(res.data.masked_numbers);
          setStep(1.5);
        } else {
          if (res.data.phone) {
            setSelectedPhone(res.data.phone);
          }
          
          setStatusModal({
            show: true,
            title: "Code Sent!",
            message: res.data.message || `We sent a verification code to ${res.data.phone || 'your phone'}.`,
            type: "success"
          });
          
          setStep(2);
          setTimer(60);
        }
      } catch (err) {
        const errorData = err.response?.data?.detail || "Verification Failed";
        setStatusModal({
          show: true,
          title: "Login Error",
          message: typeof errorData === 'object' ? JSON.stringify(errorData) : errorData,
          type: "error"
        });
      } finally {
        setIsVerifying(false);
      }
    };

   const handleVerifyOtp = async () => {
    setIsVerifying(true);
    try {
      const res = await api.post('/verify-otp', {
        student_id: studentId,
        code: otp
      });
  
      setOtp("");
  
      if (isAdminPath) {
        setStatusModal({
          show: true,
          title: "Admin Authorized",
          message: "Welcome back. You now have access to the election controls.",
          type: "success"
        });
  
        sessionStorage.setItem("commissioner_id", studentId);
  
        const role = sessionStorage.getItem("admin_role");
        if (role === "superadmin") {
          setView("superadmin");
        } else {
          setView("commission");
        }
      } else {
        setStep(3);
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail || "Invalid or Expired Code. Please try again.";
      setStatusModal({
        show: true,
        title: "Verification Failed",
        message: errorMsg,
        type: "error"
      });
      setOtp("");
    } finally {
      setIsVerifying(false);
    }
  };

    const handleSetNewPassword = async (e) => {
    e.preventDefault();
    setPasswordChangeError('');
  
    if (newPasswordForm.new_password.length < 6) {
      setPasswordChangeError('New password must be at least 6 characters.');
      return;
    }
    if (newPasswordForm.new_password !== newPasswordForm.confirm_password) {
      setPasswordChangeError('Passwords do not match.');
      return;
    }
  
    setPasswordChangeSubmitting(true);
    try {
      await api.post('/admin/set-password', {
        email:        pendingAdminEmail,
        old_password: newPasswordForm.old_password,
        new_password: newPasswordForm.new_password,
      });
  
      // Re-run login with the new password to get the role and proceed
      const res = await api.post('/verify-admin', {
        email: pendingAdminEmail,
        password: newPasswordForm.new_password,
      });
  
      sessionStorage.setItem("admin_role", res.data.role);
      if (res.data.access_token) {
        sessionStorage.setItem(ADMIN_TOKEN_KEY, res.data.access_token);
      }
      if (res.data.commissioner_id) sessionStorage.setItem("commissioner_id", res.data.commissioner_id);
      if (res.data.it_admin_id) {
        sessionStorage.setItem("it_admin_id",   res.data.it_admin_id);
        sessionStorage.setItem("it_admin_name", res.data.full_name || "");
      }
      if (res.data.financial_controller_id) {
          sessionStorage.setItem("financial_controller_id", res.data.financial_controller_id);
          sessionStorage.setItem("financial_controller_name", res.data.full_name || "");
      }
      if (res.data.overseer_id) {
          sessionStorage.setItem("overseer_id", res.data.overseer_id);
          sessionStorage.setItem("overseer_name", res.data.full_name || "");
      }
  
      setMustChangePassword(false);
      setNewPasswordForm({ old_password: '', new_password: '', confirm_password: '' });
      setView(res.data.role);
    } catch (err) {
      setPasswordChangeError(err.response?.data?.detail || 'Failed to update password.');
    } finally {
      setPasswordChangeSubmitting(false);
    }
  };
  
  const resetFlow = () => {
    // Best-effort server-side revocation — fire and forget, don't block the
    // UI on it. Client-side clearing below happens regardless, so a failed
    // revoke call never traps the user on a stuck screen.
    if (sessionStorage.getItem(ADMIN_TOKEN_KEY)) {
      api.post("/admin/logout").catch(() => {});
    }
    setStep(1);
    setView("voter");
    setIsAdminPath(false);
    setStudentId("");
    setName("");
    setOtp("");
    setMaskedNumbers([]);
    setTimer(0);
    setSelectedPhone("");
    sessionStorage.removeItem("admin_role");
    sessionStorage.removeItem(ADMIN_TOKEN_KEY);
    sessionStorage.removeItem("commissioner_id");
    sessionStorage.removeItem("it_admin_id");
    sessionStorage.removeItem("it_admin_name");
    sessionStorage.removeItem("financial_controller_id");
    sessionStorage.removeItem("financial_controller_name");
    sessionStorage.removeItem("overseer_id");
    sessionStorage.removeItem("overseer_name");
  };

  return (
    <div style={containerStyle}>
      <div style={{ 
          width: '100%', 
          maxWidth: (view === "admin" || view === "results" || view === "superadmin" || view === "commission" || view === "it_admin" || view === "financial_controller" || view === "overseer") ? '1200px' : '500px',
          margin: '0 auto',
          transition: 'max-width 0.3s ease' 
        }}>
        
        <nav className="no-print" style={navBarStyle}>
          <div style={{ display: 'flex', justifyContent: 'flex-end', width: '100%' }}>
            <button
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              style={{
                background: 'none', border: '1px solid var(--border-color)',
                borderRadius: '20px', padding: '6px 12px', cursor: 'pointer',
                fontSize: '13px', color: 'var(--text-color)',
                display: 'flex', alignItems: 'center', gap: '6px',
              }}
            >
              {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
            </button>
          </div>
          <img src={logoUrl} alt="Logo" style={logoStyle} />
          <span style={{
            color: 'var(--text-color)',
            fontSize: '13px',
            fontWeight: '700',
            letterSpacing: '1px',
            textTransform: 'uppercase',
            opacity: 0.8,
            marginTop: '-10px',
            textAlign: 'center'
          }}>
            {orgName} Election Portal
          </span>
          
          <div style={{ display: 'flex', gap: '20px', justifyContent: 'center', alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={resetFlow} style={view === "voter" && step === 1 ? activeNavBtnStyle : navBtnStyle}>
              Vote Now
            </button>
        
            <button onClick={() => setView("results")} style={view === "results" ? activeNavBtnStyle : navBtnStyle}>
              Live Results
            </button>
        
            <button onClick={() => setView("apply")} style={view === "apply" ? activeNavBtnStyle : navBtnStyle}>
              Apply
            </button>
          </div>
        </nav>

        {view === "results" && <Results apiBase={API_BASE} />}
        {view === "superadmin" && <SuperAdminDashboard onLogout={resetFlow} />}
        {view === "commission" && <CommissionDashboard onLogout={resetFlow} />}
        {view === "apply" && <ApplicantPortal apiBase={API_BASE} orgName={orgName} />}
        {view === "it_admin" && <ITAdminDashboard onLogout={resetFlow} />}
        {view === "financial_controller" && <FinancialControllerDashboard onLogout={resetFlow} />}
        {view === "overseer" && <OverseerDashboard onLogout={resetFlow} />}
        
        
        {view === "voter" && (
          <div style={{ width: '100%' }}>
            {step === 1 && (
              <div style={cardStyle}>
              <h1 style={{ textAlign: 'center', color: 'var(--text-color)' }}>
                {isAdminPath ? "Admin Login" : "Voter Login"}
              </h1>
              {!isElectionOpen && !isAdminPath && (
                <div style={noticeStyle}>
                  <strong>Notice:</strong> The election is currently closed.
                </div>
              )}
              
              {isAdminPath ? (
                <>
                  <input
                    style={inputStyle}
                    value={studentId}
                    onChange={e => setStudentId(e.target.value)}
                    placeholder="Email e.g. commissioner@example.com"
                    type="email"
                    autoComplete="email"
                  />
                  <input
                    style={inputStyle}
                    value={name}
                    onChange={e => setName(e.target.value)}
                    placeholder="Password e.g. Comm@2026!"
                    type="password"
                    autoComplete="current-password"
                  />
                </>
              ) : (
                <>
                  <input
                    style={inputStyle}
                    value={studentId}
                    onChange={e => setStudentId(e.target.value)}
                    placeholder={`Student Registration Number e.g ${placeholderText.id}`}
                  />
                  <input
                    style={inputStyle}
                    value={name}
                    onChange={e => setName(e.target.value)}
                    placeholder={`Full Name e.g ${placeholderText.name}`}
                  />
                </>
              )}
              
              <button
                onClick={() => handleVerifyIdentity()}
                disabled={(!isElectionOpen && !isAdminPath) || isVerifying}
                style={{
                  ...primaryBtnStyle,
                  backgroundColor: (isElectionOpen || isAdminPath) ? 'var(--success)' : '#bdc3c7',
                  opacity: isVerifying ? 0.7 : 1,
                  cursor: isVerifying ? 'wait' : 'pointer',
                }}
              >
                {isVerifying ? '⏳ Verifying…' : (isAdminPath ? "Login" : "Verify & Send Code")}
              </button>
              <button onClick={() => setIsAdminPath(!isAdminPath)} style={linkBtnStyle}>
                {isAdminPath ? "Switch to Voter Login" : "Are you an Admin? Login here"}
              </button>
                <div style={{ marginTop: '20px', borderTop: '1px solid var(--border-color)', paddingTop: '15px' }}>
                    <button 
                      onClick={() => setShowGuide(true)} 
                      style={{ ...linkBtnStyle, color: 'var(--success)', fontWeight: 'bold' }}
                    >
                      📖 View Sample Ballot Paper
                    </button>
                   
                    {supportPdfUrl && (
                      <a 
                        href={supportPdfUrl}
                        target="_blank" 
                        rel="noopener noreferrer"
                        style={{ 
                          ...linkBtnStyle, 
                          color: 'var(--info)', 
                          fontWeight: 'bold',
                          textDecoration: 'none',
                          display: 'block',
                          textAlign: 'center',
                          marginTop: '10px'
                        }}
                      >
                        Download Official Register (PDF)
                      </a>
                    )}
                    <a 
                      href={supportPhone ? `https://wa.me/${supportPhone}?text=Hello%20Admin,%20I%20am%20having%20issues%20with%20the%20Election%20Portal.` : "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ 
                        ...linkBtnStyle, // Spreads your existing button styles
                        color: '#25D366', // WhatsApp Green
                        fontWeight: 'bold',
                        textDecoration: 'none',
                        display: 'block', 
                        textAlign: 'center',
                        marginTop: '15px',
                        padding: '10px',
                        border: '1px solid rgba(37, 211, 102, 0.2)', // Subtle green border
                        borderRadius: '8px',
                        fontSize: '13px'
                      }}
                    >
                      Login issues? Click here to contact Support for help
                    </a>
                </div>
              </div>
            )}

            {step === 1.5 && (
              <div style={cardStyle}>
                <h2 style={{ textAlign: 'center' }}>Select Phone Number</h2>
                <p style={{ textAlign: 'center', opacity: 0.8, marginBottom: '20px' }}>Choose where to receive your code:</p>
                  {maskedNumbers.map((num, index) => (
                  <button
                    key={index}
                    onClick={() => { setSelectedPhone(num); handleVerifyIdentity(index); }}
                    disabled={isVerifying}
                    style={{ ...selectionBtnStyle, opacity: isVerifying ? 0.6 : 1, cursor: isVerifying ? 'wait' : 'pointer' }}
                  >
                    {isVerifying ? 'Sending…' : `Receive code on ${num}`}
                  </button>
                ))}
                <button onClick={() => setStep(1)} style={{ ...linkBtnStyle, color: 'var(--danger)' }}>Cancel</button>
              </div>
            )}

            {step === 2 && (
              <div style={cardStyle}>
               <OtpInput otp={otp} setOtp={setOtp} onVerify={handleVerifyOtp} phoneNumber={selectedPhone} onBack={() => setStep(1)} isSubmitting={isVerifying} />
                <div style={{ marginTop: '20px', textAlign: 'center' }}>
                  {timer > 0 ? (
                    <p style={{ fontSize: '14px', opacity: 0.7 }}>Resend in <b>{timer}s</b></p>
                  ) : (
                    <button onClick={() => handleVerifyIdentity()} style={resendBtnStyle}>Resend SMS</button>
                  )}
                </div>
              </div>
            )}

            {step === 3 && (
              <BallotBox 
                studentId={studentId} 
                onVoteSuccess={handleVoteSuccess}
                apiBase={API_BASE} 
                propCandidates={candidates}
                orgName={orgName}
              />
            )}
            
            {step === 4 && (
              <div style={{ ...cardStyle, textAlign: 'center' }}>
                <h2 style={{ color: 'var(--success)' }}>Vote Cast Successfully!</h2>
                <button onClick={resetFlow} style={{ ...primaryBtnStyle, backgroundColor: '#2ecc71' }}>Return Home</button>
              </div>
            )}
          </div>
        )}

        {mustChangePassword && (
          <div style={modalOverlayStyle}>
            <div className="modal-content" style={{ ...modalContentStyle, maxWidth: '420px' }}>
              <div style={{ fontSize: '40px', textAlign: 'center', marginBottom: '10px' }}>🔒</div>
              <h2 style={{ textAlign: 'center', marginTop: 0, color: 'var(--text-color)' }}>Set a New Password</h2>
              <p style={{ textAlign: 'center', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>
                For your security, you must set a new password before continuing.
              </p>
        
               <form onSubmit={handleSetNewPassword}>
                <input
                  type="password"
                  placeholder="Temporary password (from SMS)"
                  style={inputStyle}
                  value={newPasswordForm.old_password}
                  onChange={e => setNewPasswordForm({ ...newPasswordForm, old_password: e.target.value })}
                  disabled={passwordChangeSubmitting}
                />
                <input
                  type="password"
                  placeholder="New password (min 6 characters)"
                  style={inputStyle}
                  value={newPasswordForm.new_password}
                  onChange={e => setNewPasswordForm({ ...newPasswordForm, new_password: e.target.value })}
                  disabled={passwordChangeSubmitting}
                />
                <input
                  type="password"
                  placeholder="Confirm new password"
                  style={inputStyle}
                  value={newPasswordForm.confirm_password}
                  onChange={e => setNewPasswordForm({ ...newPasswordForm, confirm_password: e.target.value })}
                  disabled={passwordChangeSubmitting}
                />
        
                {passwordChangeError && (
                  <p style={{ color: 'var(--danger)', fontSize: '13px', textAlign: 'center', marginBottom: '10px' }}>
                    ⚠️ {passwordChangeError}
                  </p>
                )}
        
                <button
                  type="submit"
                  style={{
                    ...primaryBtnStyle,
                    backgroundColor: 'var(--success)',
                    opacity: passwordChangeSubmitting ? 0.7 : 1,
                    cursor: passwordChangeSubmitting ? 'wait' : 'pointer',
                  }}
                  disabled={passwordChangeSubmitting}
                >
                  {passwordChangeSubmitting ? '⏳ Setting password…' : 'Set Password & Continue'}
                </button>
              </form>
            </div>
          </div>
        )}
        
        {statusModal.show && (
          <div style={modalOverlayStyle}>
            <div className="modal-content" style={modalContentStyle}>
              <div style={{ fontSize: '50px', marginBottom: '10px', textAlign: 'center' }}>
                {statusModal.type === 'success' ? '📩' : '⚠️'}
              </div>
              <h2 style={{ color: statusModal.type === 'success' ? 'var(--success)' : 'var(--danger)', textAlign: 'center', marginTop: 0 }}>
                {statusModal.title}
              </h2>
              <p style={{ textAlign: 'center', marginBottom: '20px', color: 'var(--text-muted)' }}>{statusModal.message}</p>
              <button 
                onClick={() => setStatusModal({ ...statusModal, show: false })} 
                style={{ ...primaryBtnStyle, backgroundColor: statusModal.type === 'success' ? 'var(--success)' : 'var(--info)' }}
              >
                {statusModal.type === 'success' ? 'Continue' : 'Try Again'}
              </button>
            </div>
          </div>
        )}
      </div>
            {/* --- FULL PAGE BALLOT GUIDE --- */}
      {showGuide && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: '100vh',
          backgroundColor: 'var(--bg-color)',
          zIndex: 5000, // Highest z-index to cover everything
          overflowY: 'auto',
          padding: '20px'
        }}>
          <div style={{ maxWidth: '800px', margin: '0 auto' }}>
            {/* Back Button */}
            <button 
              onClick={() => setShowGuide(false)}
              style={{
                backgroundColor: '#34495e',
                color: '#fff',
                border: 'none',
                padding: '12px 20px',
                borderRadius: '8px',
                cursor: 'pointer',
                marginBottom: '20px',
                fontWeight: 'bold',
                fontSize: '16px'
              }}
            >
              ⬅ Back to Login
            </button>
      
            {/* Reusing BallotBox in Preview Mode */}
           <BallotBox 
              candidates={candidates} 
              isPreview={true} 
              apiBase={API_BASE}
              orgName={orgName}
            />
            
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#94a3b8' }}>
              <p>This is a guide. Login to cast your actual vote.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// --- STYLES ---
const containerStyle = { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', backgroundColor: 'var(--bg-color)', padding: '20px', boxSizing: 'border-box' };

const navBarStyle = { marginBottom: '30px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: '16px', padding: '15px 0', width: '100%', borderBottom: '1px solid var(--border-color)' };

const logoStyle = { height: '120px', width: 'auto', objectFit: 'contain', margin: '0 10px', filter: 'drop-shadow(0px 0px 4px rgba(241, 196, 15, 0.3))' };

const navBtnStyle = {
  padding: '10px 24px',
  backgroundColor: 'var(--brand-primary, #003366)',
  color: '#ffffff',
  border: '2px solid var(--brand-accent, #f1c40f)',
  borderRadius: '30px',
  cursor: 'pointer',
  fontWeight: '600',
  fontSize: '14px',
  transition: 'all 0.3s ease',
  boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
  textTransform: 'uppercase',
  letterSpacing: '1px'
};

const activeNavBtnStyle = {
  ...navBtnStyle,
  backgroundColor: 'var(--brand-accent, #f1c40f)',
  color: 'var(--brand-primary, #003366)',
  borderColor: 'var(--brand-primary, #003366)'
};

const cardStyle = { background: 'var(--card-bg)', color: 'var(--text-color)', padding: '30px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', border: '1px solid var(--border-color)', width: '100%', boxSizing: 'border-box' };

const inputStyle = { display: 'block', width: '100%', marginBottom: '15px', padding: '12px', borderRadius: '6px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-color)', color: 'var(--text-color)', boxSizing: 'border-box' };

const primaryBtnStyle = { width: '100%', padding: '12px', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer', transition: 'transform 0.1s' };

const noticeStyle = { backgroundColor: '#fff3cd', color: '#856404', padding: '10px', borderRadius: '6px', marginBottom: '15px', textAlign: 'center', fontSize: '14px', border: '1px solid #ffeeba' };

const modalOverlayStyle = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.9)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 3000, backdropFilter: 'blur(4px)' };

const modalContentStyle = { backgroundColor: 'var(--card-bg)', padding: '32px', borderRadius: '20px', width: '90%', maxWidth: '400px', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)', zIndex: 3001 };

const selectionBtnStyle = { width: '100%', padding: '15px', backgroundColor: '#f8f9fa', color: '#2c3e50', border: '1px solid #dee2e6', borderRadius: '8px', marginBottom: '10px', textAlign: 'left', cursor: 'pointer' };

const linkBtnStyle = { background: 'none', border: 'none', color: '#007bff', cursor: 'pointer', marginTop: '15px', width: '100%' };

const resendBtnStyle = { background: 'none', border: '1px solid #2ecc71', color: 'var(--success)', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: '600' };

export default App;
