import React, { useEffect, useRef, useState } from 'react';
import api from '../api';
import { Icon } from './icons.jsx';
import ClosedNotice, { applicationsNoticeText } from './ClosedNotice';
import { loadDraft, saveDraft, clearDraft } from '../session';
import usePolling from '../hooks/usePolling';
import { fetchBootstrap } from '../bootstrap';
import { useHelpMenu } from '../context/HelpMenuContext';
import MobileMoneyNumber from './MobileMoneyNumber';
import { usePaymentInfo } from '../paymentInfo';
import { LoadingBlock } from './Spinner.jsx';
import { trackStep } from '../analytics';
import { validateImageFile, ACCEPT_IMAGES } from '../imageFile';
import { regNo } from '../regNo';
import { resizeImage } from '../imageResize';
import {
  mapApplyError, missingFields, missingMessage, imageBlockReason, stepLabel, fileKey,
} from '../applyErrors';

// Signed, server-side upload via our own backend — replaces the old
// unsigned Cloudinary preset upload that ran straight from the browser.
// This is the one upload endpoint that has to stay public (applicants
// aren't logged in), but the backend still validates file type/size and
// rate-limits per IP, and the Cloudinary secret never touches the client.
async function uploadToCloudinary(file, { signal, onProgress } = {}) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post('/apply/upload-image', formData, {
    signal,
    onUploadProgress: onProgress ? (ev) => { if (ev.total) onProgress(Math.round((ev.loaded / ev.total) * 100)); } : undefined,
  });
  return res.data.secure_url;
}

const invalidStyle = { border: '1px solid var(--danger)' };

// Keep in sync with MANIFESTO_MAX_CHARS in backend/main.py.
const MANIFESTO_MAX_CHARS = 3000;

export default function ApplicantPortal() {
  const { openFees } = useHelpMenu();
  const startedRef = useRef(false);
  const paymentInfo = usePaymentInfo(20000);

  // Text fields of an unfinished application survive a page reload. Files
  // (candidate photo, payment proof) can't be stored, so those need to be
  // selected again.
  const [savedDraft] = useState(() => loadDraft('apply'));

  const [positions, setPositions]   = useState([]);
  const [posLoading, setPosLoading] = useState(true);
  const [uploading, setUploading]   = useState(false);
  const [submitted, setSubmitted]   = useState(false);
  const [submittedName, setSubmittedName] = useState('');
  const [error, setError]           = useState('');

  const [form, setForm] = useState({
    student_id:  savedDraft?.student_id  ?? '',
    full_name:   savedDraft?.full_name   ?? '',
    position_id: savedDraft?.position_id ?? '',
    manifesto:   savedDraft?.manifesto   ?? '',
    image:       null,
  });

  const [preview, setPreview] = useState(null);
  const [approvalPolicy, setApprovalPolicy] = useState('majority_total');
  const [electionStatus, setElectionStatus] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState(savedDraft?.payment_method ?? '');
  const [paymentProof, setPaymentProof] = useState(null);
  const [paymentProofPreview, setPaymentProofPreview] = useState(null);
  const [step, setStep] = useState(0);              // 1..4 while a submit is running
  const [uploadPct, setUploadPct] = useState(null);  // 0..100 during an upload, else null
  const [slow, setSlow] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({}); // { field: true } for every field the last submit found missing
  const formRef = useRef(null);
  const abortRef = useRef(null);
  const uploadedRef = useRef(new Map());   // fileKey -> uploaded URL, so a retry skips files that already went up
  // A restored draft only has the text fields; the files must be attached again.
  const draftRestored = Boolean(savedDraft) && Object.values(savedDraft).some(Boolean);

  useEffect(() => {
    // One startup request for positions + status (E1); falls back to the old endpoints inside fetchBootstrap.
    fetchBootstrap()
      .then(({ positions: list, status }) => {
        if (status) { setApprovalPolicy(status.approval_policy || 'majority_total'); setElectionStatus(status); }
        if (!Array.isArray(list)) { setPositions([]); return; }
        setPositions(list);
        // A restored draft may point at a position that has since been removed.
        setForm(prev => (
          prev.position_id && !list.some(p => p._id === prev.position_id)
            ? { ...prev, position_id: '' }
            : prev
        ));
      })
      .catch(() => setPositions([]))
      .finally(() => setPosLoading(false));
  }, []);

  // Warn before leaving mid-upload, and show a "slow" note when the connection drags.
  useEffect(() => {
    if (!uploading) { setSlow(false); setStep(0); setUploadPct(null); return undefined; }
    const warn = (e) => { e.preventDefault(); e.returnValue = ''; };
    const onSlow = () => setSlow(true);
    const t = setTimeout(onSlow, 10000);   // api.js emits no 'api:slow' yet, so also fall back to a timer
    window.addEventListener('beforeunload', warn);
    window.addEventListener('api:slow', onSlow);
    return () => { clearTimeout(t); window.removeEventListener('beforeunload', warn); window.removeEventListener('api:slow', onSlow); };
  }, [uploading]);

  const selectedPosition = positions.find(p => p._id === form.position_id);
  const requiredFee = Number(selectedPosition?.application_fee || 0);

  // Keep the open/closed notice and the fees current while someone fills in a long form. Only the
  // read-only status and position list are refreshed; nothing the applicant has typed is touched.
  usePolling(async () => {
    const [st, pos] = await Promise.all([
      api.get('/election-status').catch(() => null),
      api.get('/positions').catch(() => null),
    ]);
    if (st) { setApprovalPolicy(st.data.approval_policy || 'majority_total'); setElectionStatus(st.data); }
    if (pos) {
      setPositions(pos.data);
      // If the chosen position was removed meanwhile, clear it (same rule as the initial load).
      setForm(prev => (prev.position_id && !pos.data.some(p => p._id === prev.position_id) ? { ...prev, position_id: '' } : prev));
    }
  }, 20000, !submitted);

  const approvalPolicyCopy = {
    unanimous: 'Every panelist must agree. Unanimous approval is required.',
    majority_total: 'The Vetting Panel reviews all applications before any candidate appears on the ballot. A majority of the panel must agree for approval.',
    majority_cast: 'The Vetting Panel reviews all applications before any candidate appears on the ballot. Resolves once every panelist has voted. Whichever side has more wins.',
  }[approvalPolicy] || 'The Vetting Panel reviews all applications before any candidate appears on the ballot.';

  useEffect(() => {
    if (submitted) { clearDraft('apply'); return; }
    saveDraft('apply', {
      student_id:     form.student_id,
      full_name:      form.full_name,
      position_id:    form.position_id,
      manifesto:      form.manifesto,
      payment_method: paymentMethod,
    });
  }, [submitted, form.student_id, form.full_name, form.position_id, form.manifesto, paymentMethod]);

  // Reject an unsupported or oversized image the moment it is picked (instant), instead of after a slow upload.
  const rejectBadImage = (e, file) => {
    const problem = validateImageFile(file);
    if (!problem) return false;
    setError(problem);
    trackStep('apply', 'submit_blocked', imageBlockReason(file));
    e.target.value = '';   // allow picking the same file again after fixing it
    return true;
  };

  const handlePhotoChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (rejectBadImage(e, file)) return;
    setError('');
    setForm(prev => ({ ...prev, image: file }));
    setPreview(URL.createObjectURL(file));
  };

  const handlePaymentProofChange = (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (rejectBadImage(e, file)) return;
  setError('');
  setPaymentProof(file);
  setPaymentProofPreview(URL.createObjectURL(file));
  trackStep('apply', 'proof_selected');
  };
  
const busyRef = useRef(false);   // synchronous lock: `uploading` state lags a render, so a fast double tap / Enter could start two runs
const clearField = (name) => setFieldErrors(prev => (prev[name] ? { ...prev, [name]: false } : prev));

const focusField = (name) => {
  const el = formRef.current?.querySelector(`[data-field="${name}"]`);
  if (!el) return;
  el.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  el.focus?.({ preventScroll: true });
};

const cancelSubmit = () => abortRef.current?.abort();

const handleSubmit = async (e) => {
  e.preventDefault();
  if (busyRef.current) return;
  setError('');
  trackStep('apply', 'submit_clicked');

  // One pass over the whole form: list everything that is missing instead of one field per click.
  const missing = missingFields({ ...form, payment_method: paymentMethod, payment_proof: paymentProof });
  if (missing.length) {
    setFieldErrors(Object.fromEntries(missing.map(m => [m.field, true])));
    setError(missingMessage(missing));
    trackStep('apply', 'submit_blocked', 'missing_field');
    focusField(missing[0].field);
    return;
  }
  setFieldErrors({});

  busyRef.current = true;
  const controller = new AbortController();
  abortRef.current = controller;
  const hasPhoto = Boolean(form.image);
  const sid = regNo(form.student_id.trim());   // the server matches case-insensitively and stores its canonical form
  setUploading(true);
  setStep(1);
  try {
    // Gate: confirm this student_id + name is actually on the voter register
    // BEFORE spending any Cloudinary uploads on photo/payment proof.
    await api.post('/apply/check-eligibility', { student_id: sid, full_name: form.full_name.trim() }, { signal: controller.signal });

    // A file that already uploaded on an earlier attempt is not sent again.
    const upload = async (file, stepNo) => {
      const key = fileKey(file);
      const cached = uploadedRef.current.get(key);
      if (cached) return cached;
      setStep(stepNo);
      setUploadPct(0);
      const url = await uploadToCloudinary(await resizeImage(file), { signal: controller.signal, onProgress: setUploadPct });
      uploadedRef.current.set(key, url);
      setUploadPct(null);
      return url;
    };

    let image_url = '';
    if (hasPhoto) image_url = await upload(form.image, 2);

    const payment_proof_url = await upload(paymentProof, hasPhoto ? 3 : 2);

    setStep(hasPhoto ? 4 : 3);
    await api.post(`/apply`, {
      student_id:        sid,
      full_name:         form.full_name.trim(),
      position_id:       form.position_id,
      manifesto:         form.manifesto.trim(),
      image_url,
      payment_method:    paymentMethod,
      payment_proof_url,
    }, { signal: controller.signal });

    setSubmittedName(form.full_name.trim());
    setSubmitted(true);
  } catch (err) {
    if (err.response?.status === 403 && /closed|not opened|has ended/i.test(String(err.response?.data?.detail || ''))) {
      api.get('/election-status').then(r => setElectionStatus(r.data)).catch(() => {});
    }
    setError(mapApplyError(err, { online: typeof navigator === 'undefined' ? true : navigator.onLine !== false }));
  } finally {
    busyRef.current = false;
    abortRef.current = null;
    setUploading(false);
  }
};

  // ── Success screen ──
  if (submitted) {
    return (
      <div style={outerWrap} className="outer-wrap">
        <div style={{ ...card, textAlign: 'center', maxWidth: '480px', margin: '0 auto' }}>
          <h2 style={{ color: 'var(--text-color)', margin: '0 0 10px' }}>Application Submitted!</h2>
          <p style={{ opacity: 0.7, lineHeight: '1.6', marginBottom: '24px' }}>
            Thank you, <strong>{submittedName}</strong>. Your application has been received and
            is now with the Vetting Panel for review.
          </p>
          <div style={{ ...infoBox, marginBottom: '16px', textAlign: 'left' }} role="note">
            <p style={{ margin: 0, fontSize: '13px', opacity: 0.9, lineHeight: '1.6' }}>
              <strong>Follow your application on your candidate portal.</strong> A link to it is being sent by SMS
              to the phone number on your student record and may take a few minutes to arrive. Open it any time to
              see where your application stands and its outcome. If the link doesn't arrive, or you have no phone
              number on your student record, please contact the IT administrators.
            </p>
          </div>
          <div style={infoBox}>
            <p style={{ margin: 0, fontSize: '13px', opacity: 0.8 }}>
              {approvalPolicyCopy}
            </p>
          </div>
          <button
            style={{ ...greenBtn, marginTop: '24px', width: '100%' }}
            onClick={() => {
              setSubmitted(false);
              setForm({ student_id: '', full_name: '', position_id: '', manifesto: '', image: null });
              setPreview(null);
            }}
          >
            Submit Another Application
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={outerWrap} className="outer-wrap">
      <div style={{ maxWidth: '620px', margin: '0 auto', width: '100%' }}>

        {/* ── Header ── */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <h2 style={{ color: 'var(--text-color)', margin: '0 0 6px' }}>
            Apply for a Position
          </h2>
        </div>

        <ClosedNotice text={applicationsNoticeText(electionStatus)} />

        {/* Instructions for Applicants */}
        <div style={{ ...infoBox, marginBottom: '24px' }}>
          <p style={{ margin: 0, fontSize: '13px', fontWeight: 'bold', marginBottom: '8px', opacity: 0.85 }}>
            Instructions for Applicants:
          </p>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', opacity: 0.85, lineHeight: '1.9' }}>
            <li><strong>Fill and Submit Form:</strong> Complete the form below and submit your application.</li>
            <li><strong>Application Review:</strong> The Vetting Panel will review your submission.</li>
            <li><strong>Access to Portal:</strong> Check your registered phone number for an SMS link to your candidate portal.</li>
            <li><strong>Track Your Status:</strong> Use the portal link to follow your application progress and view the final outcome.</li>
            <li><strong>Need Help?</strong> If no phone number is listed on your student record, contact the IT administrators for assistance.</li>
          </ul>
        </div>

        <form ref={formRef} onSubmit={handleSubmit} style={formCol} noValidate
          onFocus={() => { if (!startedRef.current) { startedRef.current = true; trackStep('apply', 'form_started'); } }}>

          {/* Everything the applicant can change is inert while a submit is running. */}
          <fieldset disabled={uploading} style={fieldsetReset}>

          {/* ── Personal details ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Personal Details</h4>

            <label style={lbl}>Student Registration Number *</label>
            <input
              data-field="student_id"
              aria-invalid={fieldErrors.student_id ? 'true' : undefined}
              style={{ ...inp, ...(fieldErrors.student_id ? invalidStyle : null) }}
              placeholder="e.g. 22/U/IED/1086/GV"
              value={form.student_id}
              onChange={e => { clearField('student_id'); setForm(prev => ({ ...prev, student_id: e.target.value })); }}
            />

            <label style={{ ...lbl, marginTop: '12px' }}>Full Name (as on your student ID) *</label>
            <input
              data-field="full_name"
              aria-invalid={fieldErrors.full_name ? 'true' : undefined}
              style={{ ...inp, ...(fieldErrors.full_name ? invalidStyle : null) }}
              placeholder="e.g. Ayebale Elizabeth"
              value={form.full_name}
              onChange={e => { clearField('full_name'); setForm(prev => ({ ...prev, full_name: e.target.value })); }}
            />
          </div>

          {/* ── Position ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Position</h4>

            {posLoading ? (
              <LoadingBlock text="Loading available positions…" />
            ) : positions.length === 0 ? (
              <div style={{ ...infoBox, borderColor: 'color-mix(in srgb, var(--danger) 40%, transparent)' }}>
                <p style={{ margin: 0, color: 'var(--danger)', fontSize: '13px' }}>
                  No positions have been set up yet. Please check back later or contact the administration.
                </p>
              </div>
            ) : (
              <div data-field="position_id" tabIndex={-1} role="radiogroup" aria-label="Position"
                aria-invalid={fieldErrors.position_id ? 'true' : undefined}
                style={{ display: 'flex', flexDirection: 'column', gap: '10px', borderRadius: '10px', outline: 'none', ...(fieldErrors.position_id ? { boxShadow: '0 0 0 2px var(--danger)' } : null) }}>
                {positions.map((p, idx) => (
                  <div
                    key={p._id}
                    data-track={`apply-position-${idx + 1}`}
                    onClick={() => { if (uploading) return; clearField('position_id'); setForm(prev => ({ ...prev, position_id: p._id })); }}
                    style={{
                      ...positionOption,
                      border: form.position_id === p._id
                        ? '2px solid var(--success)'
                        : '1px solid var(--border-color)',
                      backgroundColor: form.position_id === p._id
                        ? 'color-mix(in srgb, var(--success) 10%, transparent)'
                        : 'var(--bg-color)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0,
                        border: form.position_id === p._id ? '2px solid var(--success)' : '2px solid var(--border-color)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {form.position_id === p._id && (
                          <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: 'var(--success)' }} />
                        )}
                      </div>
                      <div>
                        <b style={{ color: 'var(--text-color)', fontSize: '14px' }}>{p.title}</b>
                        {p.description && (
                          <p style={{ margin: '2px 0 0', fontSize: '12px', opacity: 0.6 }}>{p.description}</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Manifesto ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Your Manifesto *</h4>
            <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 10px' }}>
              Briefly explain why you are running and what you plan to do if elected.
              Aim for 50–200 words.
            </p>
            <textarea
              data-field="manifesto"
              aria-invalid={fieldErrors.manifesto ? 'true' : undefined}
              style={{ ...inp, height: '120px', resize: 'vertical', ...(fieldErrors.manifesto ? invalidStyle : null) }}
              placeholder="I am running because…"
              value={form.manifesto}
              maxLength={MANIFESTO_MAX_CHARS}
              onChange={e => { clearField('manifesto'); setForm(prev => ({ ...prev, manifesto: e.target.value })); }}
            />
            <small style={{ opacity: form.manifesto.length > MANIFESTO_MAX_CHARS * 0.9 ? 1 : 0.4, fontSize: '11px', color: form.manifesto.length >= MANIFESTO_MAX_CHARS ? 'var(--warning)' : undefined }}>
              {form.manifesto.trim().split(/\s+/).filter(Boolean).length} words · {form.manifesto.length}/{MANIFESTO_MAX_CHARS} characters
            </small>
          </div>

          {/* ── Payment Proof ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Proof of Payment *</h4>
            <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 14px' }}>
              Select your payment method and upload a screenshot or photo of the payment receipt.
            </p>

            {/* Fee for the chosen position + disclaimer */}
            {!selectedPosition ? (
              <div style={{ ...infoBox, marginBottom: '16px' }}>
                <p style={{ margin: 0, fontSize: '13px', opacity: 0.8 }}>
                  Select a position above to see the nomination fee you must pay, or{' '}
                  <button type="button" data-track="apply-fee-link" onClick={openFees} style={linkBtn}>check every position's fee first</button>.
                </p>
              </div>
            ) : requiredFee > 0 ? (
              <div style={{ ...infoBox, marginBottom: '16px', borderColor: 'var(--success)' }} role="note">
                <p style={{ margin: 0, fontSize: '13px', opacity: 0.85 }}>Nomination fee for <strong>{selectedPosition.title}</strong></p>
                <p style={{ margin: '4px 0 8px', fontSize: '22px', fontWeight: 700, color: 'var(--text-color)' }}>
                  UGX {requiredFee.toLocaleString('en-UG')}
                </p>
                <MobileMoneyNumber info={paymentInfo} style={{ margin: '0 0 10px' }} />
                <p style={{ margin: 0, fontSize: '12px', lineHeight: 1.6, opacity: 0.85 }}>
                  <strong>Important:</strong> your receipt must show a payment of this full amount. Applications with
                  an incomplete or incorrect payment amount will be rejected.
                </p>
                <button type="button" data-track="apply-fee-link" onClick={openFees} style={{ ...linkBtn, display: 'block', marginTop: '8px' }}>
                  See fees for other positions
                </button>
              </div>
            ) : null}
          
            {/* Payment method selector */}
            <label style={lbl}>Payment Method *</label>
            <div data-field="payment_method" tabIndex={-1} role="radiogroup" aria-label="Payment method"
              aria-invalid={fieldErrors.payment_method ? 'true' : undefined}
              style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px', borderRadius: '10px', outline: 'none', ...(fieldErrors.payment_method ? { boxShadow: '0 0 0 2px var(--danger)' } : null) }}>
              {['Mobile Money (MTN)', 'Mobile Money (Airtel)', 'Bank Transfer', 'Cash Receipt'].map(method => (
                <div
                  key={method}
                  data-track="apply-payment-method"
                  onClick={() => { if (uploading) return; clearField('payment_method'); setPaymentMethod(method); }}
                  style={{
                    ...positionOption,
                    border: paymentMethod === method
                      ? '2px solid var(--success)'
                      : '1px solid var(--border-color)',
                    backgroundColor: paymentMethod === method
                      ? 'color-mix(in srgb, var(--success) 10%, transparent)'
                      : 'var(--bg-color)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      width: '20px', height: '20px', borderRadius: '50%', flexShrink: 0,
                      border: paymentMethod === method
                        ? '2px solid var(--success)'
                        : '2px solid var(--border-color)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {paymentMethod === method && (
                        <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: 'var(--success)' }} />
                      )}
                    </div>
                    <span style={{ color: 'var(--text-color)', fontSize: '14px' }}>{method}</span>
                  </div>
                </div>
              ))}
            </div>
          
            {/* Proof upload */}
            <label style={lbl}>Payment Receipt / Screenshot *</label>
            {draftRestored && !paymentProof && (
              <p role="note" style={{ margin: '0 0 8px', fontSize: '12px', color: 'var(--warning)', fontWeight: 600 }}>
                Re-attach your receipt. Your typed answers were restored, but files cannot be saved.
              </p>
            )}
            <label data-track="apply-proof-upload" data-field="payment_proof" tabIndex={-1} aria-invalid={fieldErrors.payment_proof ? 'true' : undefined}
              style={{ ...photoUploadArea, minHeight: '120px', ...(fieldErrors.payment_proof ? { border: '2px dashed var(--danger)' } : null) }}>
              {paymentProofPreview ? (
                <img src={paymentProofPreview} alt="Payment proof preview" className="panel-fade-in"
                  style={{ maxWidth: '100%', maxHeight: '200px', objectFit: 'contain', borderRadius: '8px' }} />
              ) : (
                <div style={{ textAlign: 'center', opacity: 0.5 }}>
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}><Icon name="receipt" /></div>
                  <span style={{ fontSize: '13px' }}>Click to upload receipt or screenshot</span>
                  <br />
                  <span style={{ fontSize: '11px', opacity: 0.7 }}>JPG, PNG, WEBP or GIF, up to 5 MB</span>
                </div>
              )}
              <input
                type="file"
                accept={ACCEPT_IMAGES}
                style={{ display: 'none' }}
                onChange={(e) => { clearField('payment_proof'); handlePaymentProofChange(e); }}
              />
            </label>
          
            {paymentProofPreview && (
              <button
                type="button"
                style={{ ...ghostBtn, marginTop: '8px', fontSize: '12px', color: 'var(--danger)' }}
                onClick={() => { setPaymentProofPreview(null); setPaymentProof(null); }}
              >
                Remove receipt
              </button>
            )}
          </div>
          
          {/* ── Photo ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Passport Photo (optional)</h4>
            <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 12px' }}>
              A clear headshot. This will appear on the ballot paper if approved.
            </p>
            <label style={photoUploadArea}>
              {preview ? (
                <img src={preview} alt="Preview" className="panel-fade-in" style={photoPreview} />
              ) : (
                <div style={{ textAlign: 'center', opacity: 0.5 }}>
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}><Icon name="camera" /></div>
                  <span style={{ fontSize: '13px' }}>Click to upload photo</span>
                </div>
              )}
              <input
                type="file"
                accept={ACCEPT_IMAGES}
                style={{ display: 'none' }}
                onChange={handlePhotoChange}
              />
            </label>
            {preview && (
              <button
                type="button"
                style={{ ...ghostBtn, marginTop: '8px', fontSize: '12px', color: 'var(--danger)' }}
                onClick={() => { setPreview(null); setForm(prev => ({ ...prev, image: null })); }}
              >
                Remove photo
              </button>
            )}
          </div>

          </fieldset>

          {/* ── Error ── */}
          {error && (
            <div style={errorBox} role="alert">
              <Icon name="warning" /> {error}
            </div>
          )}

          {/* ── Declaration + submit ── */}
          <div style={card}>
            <div style={{ ...infoBox, marginBottom: '16px' }}>
              <p style={{ margin: 0, fontSize: '12px', opacity: 0.8, lineHeight: '1.6' }}>
                By submitting this form I confirm that the information provided is accurate,
                I consent to my details being reviewed by the Election Commission.
              </p>
            </div>
            <button
              type="submit"
              data-track="apply-submit"
              style={{ ...greenBtn, width: '100%', padding: '14px', fontSize: '15px' }}
              disabled={uploading || positions.length === 0}
              aria-busy={uploading}
            >
              {uploading
                ? <><Icon name="loading" /> {stepLabel(step || 1, Boolean(form.image))}{uploadPct != null ? ` ${uploadPct}%` : ''}</>
                : "Submit Application"}
            </button>
            {uploading && (
              <div role="status" style={{ marginTop: '10px', fontSize: '12px', textAlign: 'center' }}>
                {slow && <p style={{ margin: '0 0 8px', color: 'var(--warning)', fontWeight: 600 }}>Slow connection. Keep this page open; it can take a minute.</p>}
                <button type="button" onClick={cancelSubmit} style={ghostBtn}>Cancel</button>
              </div>
            )}
          </div>

        </form>
      </div>
    </div>
  );
}

// ── Styles ──
const outerWrap     = { width: '100%', minHeight: '100vh', backgroundColor: 'var(--bg-color)', padding: '24px 16px 96px' };   // bottom room so the floating Help ? never covers the submit button
const card          = { padding: '20px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--card-bg)', marginBottom: '16px' };
const formCol       = { display: 'flex', flexDirection: 'column', gap: '0px' };
const sectionTitle  = { margin: '0 0 14px', color: 'var(--text-color)', fontSize: '14px', fontWeight: '700' };
const lbl           = { display: 'block', fontSize: '12px', opacity: 0.65, marginBottom: '6px', fontWeight: '600' };
const inp           = { padding: '11px 13px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-color)', color: 'var(--text-color)', fontSize: '14px', width: '100%', boxSizing: 'border-box' };
const positionOption = { padding: '14px', borderRadius: '10px', cursor: 'pointer', transition: 'all 0.15s' };
const infoBox     = { padding: '12px 16px', backgroundColor: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--info) 30%, transparent)' };
const linkBtn     = { background: 'none', border: 'none', padding: 0, margin: 0, font: 'inherit', fontWeight: 700, color: 'var(--success)', textDecoration: 'underline', cursor: 'pointer' };
const errorBox    = { padding: '10px 14px', backgroundColor: 'color-mix(in srgb, var(--danger) 15%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--danger) 40%, transparent)', color: 'var(--danger)', fontSize: '12px', fontWeight: '600', marginTop: '10px' };
const photoUploadArea = { display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px dashed var(--border-color)', borderRadius: '10px', padding: '20px', cursor: 'pointer', minHeight: '100px', transition: 'border-color 0.15s, background-color 0.15s' };
const fieldsetReset = { border: 0, padding: 0, margin: 0, minWidth: 0 };
const photoPreview  = { width: '100px', height: '100px', objectFit: 'cover', borderRadius: '8px' };
const btn           = { padding: '10px 18px', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', color: '#fff' };
const greenBtn      = { ...btn, backgroundColor: 'var(--success)' };
const ghostBtn      = { padding: '8px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
