import React, { useState, useEffect } from 'react'; 
import api, { API_BASE, ADMIN_TOKEN_KEY } from './api';
import OtpInput from './components/OtpInput';
import BallotBox from './components/BallotBox';
import Results from './components/Results';
import AdminDashboard from './components/AdminDashboard';
import SuperAdminDashboard from './components/SuperAdminDashboard';
import CommissionDashboard from './components/CommissionDashboard';
import ApplicantPortal from './components/ApplicantPortal';
import ClosedNotice, { votingNoticeText } from './components/ClosedNotice';
import ITAdminDashboard from './components/ITAdminDashboard';
import FinancialControllerDashboard from './components/FinancialControllerDashboard';
import OverseerDashboard from './components/OverseerDashboard';
import { HelpMenuProvider } from './context/HelpMenuContext';
import HelpPanel from './components/HelpPanel';

// Detects whether a logo image is mostly dark (e.g. dark linework on a
// transparent PNG) so it can be inverted to stay visible against the dark
// theme's dark page background. Falls back to "don't invert" whenever the
// image can't be sampled (not loaded yet, or a CORS-tainted canvas), which
// is the safe default for arbitrary org-uploaded logos.
function useLogoNeedsInvert(logoUrl, theme) {
  // Result is keyed by the logo it was measured for, so a stale result for an old logo/theme is
  // ignored without resetting state synchronously inside the effect.
  const [result, setResult] = useState({ url: null, invert: false });
  useEffect(() => {
    if (!logoUrl || theme !== 'dark') return;
    let cancelled = false;
    const done = (invert) => { if (!cancelled) setResult({ url: logoUrl, invert }); };
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth || img.width;
        canvas.height = img.naturalHeight || img.height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
        let total = 0, count = 0;
        for (let i = 0; i < data.length; i += 4) {
          if (data[i + 3] < 10) continue; // skip transparent pixels
          total += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
          count++;
        }
        done(count > 0 && total / count < 100); // mostly dark ink
      } catch {
        done(false); // CORS-tainted or unreadable — fail safe
      }
    };
    img.onerror = () => done(false);
    img.src = logoUrl;
    return () => { cancelled = true; };
  }, [logoUrl, theme]);
  return Boolean(logoUrl) && theme === 'dark' && result.url === logoUrl && result.invert;
}
import { FabTrigger } from './components/HelpTriggers';
import usePolling from './hooks/usePolling';
import { Icon } from './components/icons.jsx';
import TurnstileWidget from './components/TurnstileWidget';
import { turnstileConfigured } from './supportLink';
import {
  restoreAdminView, loadPublicView, savePublicView,
  loadVoterProgress, saveVoterProgress, clearVoterProgress, clearVoterSession,
  saveVoterToken, clearVoterToken, loadResendSeconds, saveResendDeadline,
  clearAdminSession, markPasswordChangePending, clearPasswordChangePending,
} from './session';

// Sample IDs/names cycled in the login placeholder animation.
const examples = [
  { id: "23/U/BCS/10245/GV", name: "Ayebale Elizabeth" },
  { id: "22/U/ISD/08940/PD", name: "Namusoke Dorothy Nalwadda" },
  { id: "23/U/AGE/11223/GV", name: "Kaggwa Paul" },
  { id: "21/U/BSE/44556/PE", name: "Sserwadda Valentino" },
  { id: "23/U/BPH/00341/GV", name: "Bakanansa Jesca" }
];

function App() {
  const [supportContacts, setSupportContacts] = useState([]);
  const [supportPhone, setSupportPhone] = useState("");
  const [showGuide, setShowGuide] = useState(false); // New state for Guide
  const [candidates, setCandidates] = useState([]); // To store candidates for preview
  // Decide ONCE, before the first render, where to resume after a reload
  // (pull-to-refresh, F5, a discarded background tab). Everything below used
  // to start from "voter login, step 1" unconditionally, which dropped even
  // signed-in admins and OTP-verified voters back on the login screen.
  // Priority: a public page (Results/Apply) the person was on, then a
  // still-valid admin session, then a voter mid-flow.
  const [restored] = useState(() => {
    const adminView = restoreAdminView();          // null if none / expired
    const pub = loadPublicView();
    if (pub) return { view: pub, adminView };
    if (adminView) return { view: adminView, adminView };
    const vp = loadVoterProgress();
    if (vp) return { view: "voter", ...vp };
    return {};
  });
  const [step, setStep] = useState(restored.step || 1); 
  const [view, setView] = useState(restored.view || "voter"); 
  // Mirrors sessionStorage's "admin_role" in React state so the nav can react
  // to it. Lets a logged-in admin who has navigated to Results/Apply/Vote get
  // back to their dashboard with one click, instead of refreshing or hitting
  // "Vote Now" — which calls resetFlow() and signs them out entirely.
  const [adminRole, setAdminRole] = useState(restored.adminView || null);
  const [studentId, setStudentId] = useState(restored.studentId || "");
  const [name, setName] = useState("");
  const [otp, setOtp] = useState("");
  const [placeholderText, setPlaceholderText] = useState({ id: "", name: "" });
  const [isDeleting, setIsDeleting] = useState(false);
  const [loopNum, setLoopNum] = useState(0);
  const [typingSpeed, setTypingSpeed] = useState(150);
  const [isAdminPath, setIsAdminPath] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [needsTotp, setNeedsTotp] = useState(false);
  const [isElectionOpen, setIsElectionOpen] = useState(true);
  const [electionStatus, setElectionStatus] = useState(null);
  // Cloudflare Turnstile (voter code requests only). The token is single-use, so every attempt
  // bumps `captchaKey` to fetch a fresh one. `captchaForced` flips on when the server asks for the
  // check even though the org mode isn't "on" (adaptive on a flagged IP, or under attack).
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaKey, setCaptchaKey] = useState(0);
  const [captchaForced, setCaptchaForced] = useState(false);
  const [maskedNumbers, setMaskedNumbers] = useState([]);
  const [orgName, setOrgName] = useState(import.meta.env.VITE_ELECTION_NAME || "");
  const [timer, setTimer] = useState(() => (restored.step === 2 ? loadResendSeconds() : 0));
  const [selectedPhone, setSelectedPhone] = useState(restored.selectedPhone || "");
  const [isVerifying, setIsVerifying] = useState(false);
  const [statusModal, setStatusModal] = useState({ 
    show: false, 
    title: '', 
    message: '', 
    type: 'success' 
  });
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [pendingAdminEmail, setPendingAdminEmail]     = useState('');
  // Captured from the login form the moment the temp-password login succeeds,
  // so the forced password-change modal doesn't have to ask the admin to
  // retype the code they just entered. Still sent to /admin/set-password as
  // old_password so the backend keeps verifying it server-side.
  const [pendingTempPassword, setPendingTempPassword] = useState('');
  const [newPasswordForm, setNewPasswordForm]         = useState({ new_password: '', confirm_password: '' });
  const [passwordChangeError, setPasswordChangeError] = useState('');
  const [passwordChangeSubmitting, setPasswordChangeSubmitting] = useState(false);
  // Instant, zero-network fallback for the splash: baked into the build per
  // org (same pattern as VITE_ORG_SLUG in api.js), so the very first paint
  // already has the right name/logo instead of a generic placeholder while
  // /superadmin/branding is still in flight. The Mongo-backed branding call
  // still runs and can override these (colors, an updated logo, etc.) — env
  // vars just mean there's nothing to wait on for the first frame.
  const [logoUrl, setLogoUrl] = useState(import.meta.env.VITE_LOGO_URL || "");
  // Gates the very first paint of the real app. "Ready" here means two
  // things are both true: the backend is actually reachable (checked via
  // /health, not /superadmin/branding — a plain ping, unauthenticated,
  // org-exempt, so it's the fastest true signal that "this tenant's backend
  // is up" without pulling in branding/auth concerns), AND a short minimum
  // floor has elapsed so the splash never flashes on/off in one frame on a
  // fast connection. It does NOT wait a fixed period regardless of state —
  // that would add fake latency for fast users and false confidence for
  // slow ones. See bootExiting below for the animated hand-off.
  const [bootReady, setBootReady] = useState(false);
  const [bootExiting, setBootExiting] = useState(false);
  // Flips true once the wait has run past what a warm backend would ever
  // take — only then does the splash admit it might be a cold start, so a
  // normal warm load never sees this copy at all.
  const [bootSlow, setBootSlow] = useState(false);
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('theme');
    if (saved === 'light' || saved === 'dark') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const logoNeedsInvert = useLogoNeedsInvert(logoUrl, theme);
  const logoStyle = {
    height: '120px',
    width: 'auto',
    objectFit: 'contain',
    margin: '0 10px',
    filter: logoNeedsInvert
      ? 'invert(1) hue-rotate(180deg) drop-shadow(0px 0px 4px rgba(241, 196, 15, 0.3))'
      : 'drop-shadow(0px 0px 4px rgba(241, 196, 15, 0.3))',
  };

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  
// --- USEEFFECTS ---
useEffect(() => {
  // Render's free tier spins the backend down when idle and can take 30-50+
  // seconds to cold-start on the next request. That makes a fixed timeout
  // actively harmful here: releasing the splash before the backend is truly
  // up doesn't make the wait shorter, it just drops the visitor into a
  // normal-looking login screen that then fails every request for the next
  // 40 seconds — which reads as far more broken than staying on the splash.
  // So this polls /health for real success instead of giving up on a clock,
  // and the copy is honest about *why* it's slow past the point where a
  // warm backend would have already answered.
  const BOOT_MIN_MS = 500;       // floor so a warm/cached response never flickers
  const POLL_INTERVAL_MS = 2500; // spacing between retries while cold-starting
  const SLOW_HINT_MS = 6000;     // past this, a warm backend would've answered — say so
  const EXIT_ANIM_MS = 350;      // must match the CSS transition on the splash

  const bootStart = Date.now();
  let cancelled = false;
  let pollTimer = null;

  const slowHintTimer = setTimeout(() => {
    if (!cancelled) setBootSlow(true);
  }, SLOW_HINT_MS);

  const finish = () => {
    if (cancelled) return;
    cancelled = true;
    clearTimeout(slowHintTimer);
    clearTimeout(pollTimer);
    const elapsed = Date.now() - bootStart;
    const wait = Math.max(0, BOOT_MIN_MS - elapsed);
    setTimeout(() => {
      // Animate out rather than unmounting straight away, so "ready" reads
      // as a deliberate hand-off instead of a jump-cut.
      setBootExiting(true);
      setTimeout(() => setBootReady(true), EXIT_ANIM_MS);
    }, wait);
  };

  const poll = () => {
    api.get('/health').then(finish).catch(() => {
      if (!cancelled) pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
    });
  };
  poll();

  api.get('/superadmin/branding').then(res => {
    if (res.data.support_phone) setSupportPhone(res.data.support_phone);
    if (Array.isArray(res.data.support_contacts)) setSupportContacts(res.data.support_contacts);
    if (res.data.logo_url) {
      setLogoUrl(res.data.logo_url);
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
  }).catch(() => {
    // Branding is enrichment, not a boot gate — the env fallback (already
    // showing) is enough if this fails. Silent by design.
  });

  return () => { cancelled = true; clearTimeout(slowHintTimer); clearTimeout(pollTimer); };
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

  }, [placeholderText, isDeleting, loopNum, typingSpeed, studentId, name]);
  
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await api.get('/election-status');
        setIsElectionOpen(res.data.is_open);
        setElectionStatus(res.data);
      } catch {
        console.error("Could not fetch election status");
      }
    };
    checkStatus();
  }, []);

  // Voting/applications can open or close while a page is open; keep the button and notice current.
  usePolling(async () => {
    const res = await api.get('/election-status');
    setIsElectionOpen(res.data.is_open);
    setElectionStatus(res.data);
  }, 30000);

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

  // --- SESSION PERSISTENCE ---
  // Remember which public page is open so a reload doesn't bounce off it.
  useEffect(() => { savePublicView(view); }, [view]);

  // Remember the voter's place in the flow (never the OTP itself). Going back
  // to step 1 / 1.5 means the session is over, so forget it.
  useEffect(() => {
    if (view !== "voter" || isAdminPath) return;
    if ([2, 3, 4].includes(step) && studentId) {
      saveVoterProgress({ step, studentId, selectedPhone });
    } else if (step === 1 || step === 1.5) {
      clearVoterSession();
    }
  }, [view, step, studentId, selectedPhone, isAdminPath]);

  // --- HANDLERS ---
  // BallotBox calls this on a 401 from /vote-bulk (token missing/expired/
  // replaced by a newer login). Their ballot picks are kept in sessionStorage.
  const handleSessionExpired = (detail) => {
    clearVoterSession();
    setOtp("");
    setStep(1);
    setStatusModal({
      show: true,
      title: "Session Expired",
      message: (typeof detail === "string" && detail) ||
        "Your voting session has expired. Please verify again — your selections have been kept.",
      type: "error"
    });
  };

  const handleVoteSuccess = () => {
    // 1. Create the cookie
    const expiry = new Date();
    expiry.setSeconds(expiry.getSeconds() + 86400); 
    
    // 2. Save it to the browser
    document.cookie = `voted_status=true; expires=${expiry.toUTCString()}; path=/; SameSite=Lax`;

    // 3. The one-time voting token is spent — drop it and move to the final screen
    clearVoterToken();
    setStep(4);
  };

const needsCaptcha = !isAdminPath && turnstileConfigured
    && (captchaForced || electionStatus?.turnstile_mode === 'on');
  const captchaPending = needsCaptcha && !captchaToken;

const handleVerifyIdentity = async (selectedIdx = null) => {
      setIsVerifying(true);
      try {
        const endpoint = isAdminPath ? "/verify-admin" : "/verify-identity";
      
        const payload = isAdminPath
          ? { email: studentId, password: name, totp_code: totpCode || undefined }
          : { student_id: studentId, full_name: name, phone_index: selectedIdx, turnstile_token: captchaToken || undefined };
    
        const res = await api.post(endpoint, payload);
  
        if (res.data.bypass === true) {
          sessionStorage.setItem("admin_role", res.data.role);
          setAdminRole(res.data.role);
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
            markPasswordChangePending();
            setPendingAdminEmail(studentId);
            setPendingTempPassword(name); // `name` holds the password field for the admin login path
            setMustChangePassword(true);
            return;
          }
        
          setView(res.data.role);
          return;
        }
        sessionStorage.setItem("admin_role",res.data.role || "commission");
        setAdminRole(res.data.role || "commission");
  
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
          saveResendDeadline(60);
        }
      } catch (err) {
        // Superadmin credentials matched but no code was entered yet — reveal
        // the field and let them submit again, rather than showing this as
        // a login failure. This is the only path that turns needsTotp on,
        // so the field only ever appears once email+password have actually
        // matched the superadmin account.
        if (isAdminPath && err.response?.status === 428 && err.response?.data?.detail === "totp_required") {
          setNeedsTotp(true);
          setIsVerifying(false);
          return;
        }
        if (!isAdminPath && err.response?.data?.reason === "captcha_required") setCaptchaForced(true);
        const errorData = err.response?.data?.detail || "Verification Failed";
        // The schedule changed after this page loaded: re-read the status so the notice says
        // the right thing (not started yet vs. ended) instead of guessing from the error text.
        if (!isAdminPath && err.response?.status === 403 && /closed|has ended/i.test(String(errorData))) {
          api.get('/election-status').then(r => { setIsElectionOpen(r.data.is_open); setElectionStatus(r.data); }).catch(() => {});
        }
        setStatusModal({
          show: true,
          title: "Login Error",
          message: typeof errorData === 'object' ? JSON.stringify(errorData) : errorData,
          type: "error"
        });
      } finally {
        setIsVerifying(false);
        if (!isAdminPath) { setCaptchaToken(""); setCaptchaKey(k => k + 1); }
      }
    };

   const handleVerifyOtp = async () => {
    setIsVerifying(true);
    try {
      const otpRes = await api.post('/verify-otp', {
        student_id: studentId,
        code: otp
      });

      // The server issues a one-time voting token on a correct OTP; the
      // /vote-* calls send it (see api.js) and it lets a reload resume the ballot.
      if (!isAdminPath && otpRes.data?.voter_token) saveVoterToken(otpRes.data.voter_token);
  
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
        old_password: pendingTempPassword,
        new_password: newPasswordForm.new_password,
      });
  
      // Re-run login with the new password to get the role and proceed
      const res = await api.post('/verify-admin', {
        email: pendingAdminEmail,
        password: newPasswordForm.new_password,
      });
  
      sessionStorage.setItem("admin_role", res.data.role);
      setAdminRole(res.data.role);
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
  
      clearPasswordChangePending();
      setMustChangePassword(false);
      setPendingTempPassword('');
      setNewPasswordForm({ new_password: '', confirm_password: '' });
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
    setTotpCode("");
    setNeedsTotp(false);
    setMaskedNumbers([]);
    setTimer(0);
    setSelectedPhone("");
    setAdminRole(null);
    // Full sign-out: admin token/role/ids/remembered tabs, the voter session
    // and saved ballot picks, and the remembered public page.
    clearAdminSession();
    clearVoterProgress();
    savePublicView(null);
  };

  if (!bootReady) {
    return <BootSplash orgName={orgName} logoUrl={logoUrl} exiting={bootExiting} slow={bootSlow} />;
  }

  return (
    <HelpMenuProvider>
    <div style={containerStyle}>
      {view === "voter" && (
        <>
          <HelpPanel
            supportPhone={supportPhone}
            supportContacts={supportContacts}
            orgName={orgName}
            onShowGuide={() => setShowGuide(true)}
          />
          {/* Ballot page (step 3) puts Help inside its own footer bar via
              <InlineHelpButton /> — see BallotBox.jsx — so the floating
              trigger only renders when nothing else owns that space. */}
          {step !== 3 && <FabTrigger />}
        </>
      )}
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
              {theme === 'dark' ? <>Light</> : <>Dark</>}
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

            {/* Deliberately NOT shown while view === "voter": that flow is
                someone actively proving they're a different identity (via
                OTP), and a leftover admin session from earlier in the tab
                has nothing to do with who's typing right now. Showing this
                shortcut there meant anyone who knew an admin's voter
                credentials (student ID + name — not a secret) could open
                the voter OTP screen and skip straight into the admin
                dashboard with zero re-authentication, on any device/tab
                where an admin had once logged in and not explicitly logged
                out. Restricted to results/apply — the two read-only pages
                this was actually built for. */}
            {adminRole && (view === "results" || view === "apply") && (
              <button onClick={() => setView(adminRole)} style={backToAdminBtnStyle}>
                Back to Admin
              </button>
            )}
          </div>
        </nav>

        {view === "results" && <Results apiBase={API_BASE} />}
        {view === "superadmin" && <SuperAdminDashboard onLogout={resetFlow} />}
        {view === "commission" && <CommissionDashboard onLogout={resetFlow} />}
        {view === "apply" && <ApplicantPortal />}
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
              {!isAdminPath && <ClosedNotice text={votingNoticeText(electionStatus)} />}
              
              {isAdminPath ? (
                <>
                  <input
                    style={inputStyle}
                    value={studentId}
                    onChange={e => { setStudentId(e.target.value); setNeedsTotp(false); setTotpCode(""); }}
                    placeholder="Email e.g. commissioner@example.com"
                    type="email"
                    autoComplete="email"
                  />
                  <input
                    style={inputStyle}
                    value={name}
                    onChange={e => { setName(e.target.value); setNeedsTotp(false); setTotpCode(""); }}
                    placeholder="Password e.g. Comm@2026!"
                    type="password"
                    autoComplete="current-password"
                  />
                  {needsTotp && (
                    <input
                      style={inputStyle}
                      value={totpCode}
                      onChange={e => setTotpCode(e.target.value)}
                      placeholder="Authenticator code"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      autoFocus
                    />
                  )}
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
              
              {needsCaptcha && <TurnstileWidget onToken={setCaptchaToken} resetKey={captchaKey} />}
              <button
                onClick={() => handleVerifyIdentity()}
                disabled={(!isElectionOpen && !isAdminPath) || isVerifying || captchaPending}
                style={{
                  ...primaryBtnStyle,
                  backgroundColor: (isElectionOpen || isAdminPath) ? 'var(--success)' : '#bdc3c7',
                  opacity: isVerifying ? 0.7 : 1,
                  cursor: isVerifying ? 'wait' : 'pointer',
                }}
              >
                {isVerifying ? <><Icon name="loading" /> Verifying…</> : (isAdminPath ? "Login" : "Verify & Send Code")}
              </button>
              <button onClick={() => { setIsAdminPath(!isAdminPath); setNeedsTotp(false); setTotpCode(""); }} style={linkBtnStyle}>
                {isAdminPath ? "Switch to Voter Login" : "Are you an Admin? Login here"}
              </button>
              </div>
            )}

            {step === 1.5 && (
              <div style={cardStyle}>
                <h2 style={{ textAlign: 'center' }}>Select Phone Number</h2>
                <p style={{ textAlign: 'center', opacity: 0.8, marginBottom: '20px' }}>Choose where to receive your code:</p>
                {needsCaptcha && <TurnstileWidget onToken={setCaptchaToken} resetKey={captchaKey} />}
                  {maskedNumbers.map((num, index) => (
                  <button
                    key={index}
                    onClick={() => { setSelectedPhone(num); handleVerifyIdentity(index); }}
                    disabled={isVerifying || captchaPending}
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
               <OtpInput otp={otp} setOtp={setOtp} onVerify={handleVerifyOtp} phoneNumber={selectedPhone} onBack={() => setStep(1)} isSubmitting={isVerifying}
                 supportPhone={supportPhone || supportContacts[0]?.contacts?.[0]?.link || ''} orgName={orgName} studentId={studentId} />
                <div style={{ marginTop: '20px', textAlign: 'center' }}>
                  {timer > 0 ? (
                    <p style={{ fontSize: '14px', opacity: 0.7 }}>Resend in <b>{timer}s</b></p>
                  ) : (
                    <>
                      {needsCaptcha && <TurnstileWidget onToken={setCaptchaToken} resetKey={captchaKey} />}
                      <button onClick={() => handleVerifyIdentity()} disabled={captchaPending || isVerifying}
                        style={{ ...resendBtnStyle, opacity: captchaPending ? 0.5 : 1 }}>Resend SMS</button>
                    </>
                  )}
                </div>
              </div>
            )}

            {step === 3 && (
              <BallotBox 
                studentId={studentId} 
                onVoteSuccess={handleVoteSuccess}
                onSessionExpired={handleSessionExpired}
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
              <h2 style={{ textAlign: 'center', marginTop: 0, color: 'var(--text-color)' }}>Set a New Password</h2>
              <p style={{ textAlign: 'center', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>
                For your security, you must set a new password before continuing.
              </p>
        
               <form onSubmit={handleSetNewPassword}>
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
                    <Icon name="warning" /> {passwordChangeError}
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
                  {passwordChangeSubmitting ? <><Icon name="loading" /> Setting password…</> : 'Set Password & Continue'}
                </button>
              </form>
            </div>
          </div>
        )}
        
        {statusModal.show && (
          <div style={modalOverlayStyle}>
            <div className="modal-content" style={modalContentStyle}>
              <div style={{ fontSize: '50px', marginBottom: '10px', textAlign: 'center' }}>
                {statusModal.type === 'success' ? <Icon name="success" /> : <Icon name="warning" />}
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
              Back to Login
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
    </HelpMenuProvider>
  );
}

// --- STYLES ---
// A boot-time splash, shown until /health confirms this tenant's backend is
// actually up (see the effect above). The name/logo come from build-time env
// vars (VITE_ELECTION_NAME / VITE_LOGO_URL) so they're present on the very
// first frame — no network round-trip to wait on for those. If the Mongo-
// backed /superadmin/branding call later returns a different name/logo,
// App.jsx updates the props in place; since the splash is still showing the
// same *kind* of content (a name, a mark), that swap doesn't need its own
// transition. "exiting" drives the hand-off animation to the real app once
// /health resolves — same pattern as eregistry.ursb.go.ug's
// "Initializing secure session" screen.
function BootSplash({ orgName, logoUrl, exiting, slow }) {
  const known = Boolean(orgName || logoUrl);
  return (
    <div style={{ ...bootWrapStyle, ...(exiting ? bootWrapExitStyle : null) }}>
      <div style={bootCardStyle}>
        <div style={bootSpinnerStyle}>
          {logoUrl
            ? <img src={logoUrl} alt="" style={{ width: '46px', height: '46px', objectFit: 'contain', borderRadius: '8px' }} />
            : <span style={bootSpinnerRingStyle} />}
        </div>
        <h1 style={bootTitleStyle}>{orgName || 'Election Portal'}</h1>
        <p style={bootSubtitleStyle}>
          {slow
            ? 'The server is starting up after a period of inactivity — this can take up to a minute. Thanks for your patience.'
            : known
              ? 'Central register for this election\u2019s voters and results'
              : 'Loading election details…'}
        </p>
        <div style={bootStatusRowStyle}>
          <span style={{ ...bootDotStyle, background: slow ? 'var(--warning, #eab308)' : known ? 'var(--success, #22c55e)' : 'var(--warning, #eab308)' }} />
          {slow ? 'STARTING SERVER' : known ? 'INITIALIZING SECURE SESSION' : 'CONNECTING'}
        </div>
      </div>
    </div>
  );
}

const bootWrapStyle = {
  position: 'fixed', inset: 0, zIndex: 9999,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: 'var(--bg-color, #f4f6fb)', padding: '20px', boxSizing: 'border-box',
  opacity: 1, transform: 'scale(1)',
  transition: 'opacity 0.35s ease, transform 0.35s ease',
};

// Applied for the final 350ms (EXIT_ANIM_MS in the boot effect, above) once
// /health has resolved — a soft fade + scale rather than a hard unmount, so
// the real app appears as a deliberate hand-off instead of a jump-cut.
const bootWrapExitStyle = {
  opacity: 0, transform: 'scale(1.02)',
  pointerEvents: 'none',
};
const bootCardStyle = {
  width: '100%', maxWidth: '380px', textAlign: 'center',
  background: 'var(--card-bg, #fff)', borderRadius: '20px',
  padding: '48px 32px', boxShadow: '0 10px 40px rgba(0,0,0,0.08)',
  border: '1px solid var(--border-color, #e5e9f2)',
};
const bootSpinnerStyle = {
  width: '64px', height: '64px', margin: '0 auto 22px',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};
const bootSpinnerRingStyle = {
  display: 'block', width: '56px', height: '56px', borderRadius: '50%',
  border: '3px solid transparent',
  borderTopColor: 'var(--brand-primary, #2563eb)',
  borderBottomColor: 'var(--brand-primary, #2563eb)',
  animation: 'boot-spin 0.9s linear infinite',
};
const bootTitleStyle = {
  margin: '0 0 10px', fontSize: '26px', fontWeight: 800,
  color: 'var(--brand-primary, #1d4ed8)', letterSpacing: '0.3px',
};
const bootSubtitleStyle = {
  margin: '0 0 22px', fontSize: '14px', lineHeight: 1.5,
  color: 'var(--text-muted, #64748b)',
};
const bootStatusRowStyle = {
  display: 'inline-flex', alignItems: 'center', gap: '8px',
  fontSize: '11px', fontWeight: 700, letterSpacing: '1px',
  color: 'var(--text-muted, #64748b)',
};
const bootDotStyle = { width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0 };

// The keyframes are injected once, globally — App.jsx has no CSS module of
// its own, and this animation is only ever used by BootSplash.
if (typeof document !== 'undefined' && !document.getElementById('boot-spin-keyframes')) {
  const style = document.createElement('style');
  style.id = 'boot-spin-keyframes';
  style.textContent = '@keyframes boot-spin { to { transform: rotate(360deg); } }';
  document.head.appendChild(style);
}

const containerStyle = { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', backgroundColor: 'var(--bg-color)', padding: '20px', boxSizing: 'border-box' };

const navBarStyle = { marginBottom: '30px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: '16px', padding: '15px 0', width: '100%', borderBottom: '1px solid var(--border-color)' };


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

// Only shown when an admin session exists (sessionStorage's "admin_role")
// and the visitor has clicked away from their dashboard — e.g. to preview
// Live Results — so they never have to refresh or use "Vote Now" (which
// signs them out) just to get back to where they were logged in.
const backToAdminBtnStyle = {
  ...navBtnStyle,
  display: 'flex',
  alignItems: 'center',
  gap: '6px',
  backgroundColor: 'transparent',
  color: 'var(--brand-accent, #f1c40f)',
  borderStyle: 'dashed',
};

const cardStyle = { background: 'var(--card-bg)', color: 'var(--text-color)', padding: '30px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', border: '1px solid var(--border-color)', width: '100%', boxSizing: 'border-box' };

const inputStyle = { display: 'block', width: '100%', marginBottom: '15px', padding: '12px', borderRadius: '6px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-color)', color: 'var(--text-color)', boxSizing: 'border-box' };

const primaryBtnStyle = { width: '100%', padding: '12px', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer', transition: 'transform 0.1s' };


const modalOverlayStyle = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.9)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 3000, backdropFilter: 'blur(4px)' };

const modalContentStyle = { backgroundColor: 'var(--card-bg)', padding: '32px', borderRadius: '20px', width: '90%', maxWidth: '400px', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)', zIndex: 3001 };

const selectionBtnStyle = { width: '100%', padding: '15px', backgroundColor: '#f8f9fa', color: '#2c3e50', border: '1px solid #dee2e6', borderRadius: '8px', marginBottom: '10px', textAlign: 'left', cursor: 'pointer' };

const linkBtnStyle = { background: 'none', border: 'none', color: '#007bff', cursor: 'pointer', marginTop: '15px', width: '100%' };

const resendBtnStyle = { background: 'none', border: '1px solid #2ecc71', color: 'var(--success)', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: '600' };

export default App;
