import React, { useEffect, useRef, useState } from 'react';
import { useIdText } from '../idText';
import api from '../api';
import { Icon } from './icons.jsx';
import ClosedNotice, { applicationsNoticeText } from './ClosedNotice';
import { loadDraft, saveDraft, clearDraft } from '../session';
import usePolling from '../hooks/usePolling';
import { fetchBootstrap } from '../bootstrap';
import { useHelpMenu } from '../context/HelpMenuContext';
import MobileMoneyNumber from './MobileMoneyNumber';
import { usePaymentInfo } from '../paymentInfo';
import { useNominationForm } from '../nominationForm';
import { LoadingBlock } from './Spinner.jsx';
import { trackStep } from '../analytics';
import { validateImageFile, ACCEPT_IMAGES } from '../imageFile';
import { regNo } from '../regNo';
import { getTemplate } from '../template';
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

async function uploadNominationDocument(file, { signal, onProgress } = {}) {
  const formData = new FormData(); formData.append('file', file);
  const res = await api.post('/apply/upload-document', formData, { signal,
    onUploadProgress: onProgress ? (ev) => { if (ev.total) onProgress(Math.round((ev.loaded / ev.total) * 100)); } : undefined,
  });
  return res.data;
}

const invalidStyle = { border: '1px solid var(--danger)' };

// Keep in sync with MANIFESTO_MAX_CHARS in backend/main.py.
const MANIFESTO_MAX_CHARS = 3000;

export default function ApplicantPortal() {
  const idText = useIdText();
  const { openFees } = useHelpMenu();
  const startedRef = useRef(false);
  const paymentInfo = usePaymentInfo(20000);
  const nominationForm = useNominationForm(20000);

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
    phone:       '',   // only asked for when the org turns on collect_phone; deliberately not saved in the draft
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
  const [nominationFile, setNominationFile] = useState(null);
  const [nominationUploadId, setNominationUploadId] = useState('');
  const [step, setStep] = useState(0);              // 1..4 while a submit is running
  const [uploadPct, setUploadPct] = useState(null);  // 0..100 during an upload, else null
  const [slow, setSlow] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({}); // { field: true } for every field the last submit found missing
  const formRef = useRef(null);
  const abortRef = useRef(null);
  const uploadedRef = useRef(new Map());   // fileKey -> uploaded value, so a retry skips files already sent
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
  
const handleNominationChange = (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const ext = file.name?.toLowerCase().endsWith('.docx') ? 'docx' : (file.name?.toLowerCase().endsWith('.pdf') ? 'pdf' : '');
  if (!ext || !(nominationForm.accepted_types || ['pdf']).includes(ext)) { setError('That nomination-form file type is not supported.'); e.target.value=''; return; }
  if (file.size > Number(nominationForm.max_mb || 5) * 1024 * 1024) { setError(`That nomination form is over ${nominationForm.max_mb || 5} MB.`); e.target.value=''; return; }
  clearField('nomination_form'); setError(''); setNominationFile(file); setNominationUploadId('');
  uploadedRef.current.forEach((_, key) => { if (key.startsWith('nomination|')) uploadedRef.current.delete(key); });
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
  const missing = missingFields({ ...form, payment_method: paymentMethod, payment_proof: paymentProof, nomination_form: nominationForm.enabled && nominationFile }, { nominationRequired: Boolean(nominationForm.enabled && nominationForm.required), phoneRequired: Boolean(nominationForm.collect_phone) });
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
    await api.post('/apply/check-eligibility', { student_id: sid, full_name: form.full_name.trim(), ...(nominationForm.collect_phone ? { phone: form.phone.trim() } : {}) }, { signal: controller.signal });

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

    let nomination_upload_id = '';
    if (nominationForm.enabled && nominationFile) {
      const nk = `nomination|${fileKey(nominationFile)}`;
      const cachedNom = uploadedRef.current.get(nk);
      if (cachedNom) { nomination_upload_id = cachedNom.upload_id; }
      else {
        setStep(hasPhoto ? 3 : 2); setUploadPct(0);
        const uploaded = await uploadNominationDocument(nominationFile, { signal: controller.signal, onProgress: setUploadPct });
        nomination_upload_id = uploaded.upload_id; uploadedRef.current.set(nk, uploaded); setNominationUploadId(nomination_upload_id); setUploadPct(null);
      }
    } else if (nominationUploadId) {
      nomination_upload_id = nominationUploadId;
    }

    const paymentStep = hasPhoto ? (nominationForm.enabled ? 4 : 3) : (nominationForm.enabled ? 3 : 2);
    const submitStep = hasPhoto ? (nominationForm.enabled ? 5 : 4) : (nominationForm.enabled ? 4 : 3);
    const payment_proof_url = await upload(paymentProof, paymentStep);

    setStep(submitStep);
    await api.post(`/apply`, {
      student_id:        sid,
      full_name:         form.full_name.trim(),
      position_id:       form.position_id,
      manifesto:         form.manifesto.trim(),
      image_url,
      payment_method:    paymentMethod,
      payment_proof_url,
      nomination_upload_id,
      ...(nominationForm.collect_phone ? { phone: form.phone.trim() } : {}),
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

  // ── Template seam (BP-T6). Called after every hook. Default: today's inline look, byte for byte.
  // Blueprint: class hooks from the template; inline colour/shape styles are dropped (sx) so the classes can win. ──
  const bp = getTemplate();
  const k = bp?.cls;
  const sx = (s, b) => (bp ? b : s);
  const sel = (on) => (bp && on ? ` ${k.on}` : '');

  // ── Success screen ──
  if (submitted) {
    return (
      <div style={sx(outerWrap)} className="outer-wrap">
        <div style={sx({ ...card, textAlign: 'center', maxWidth: '480px', margin: '0 auto' })} className={k ? `${k.card} ${k.done}` : undefined}>
          <h2 style={sx({ color: 'var(--text-color)', margin: '0 0 10px' })}>Application Submitted!</h2>
          <p style={sx({ opacity: 0.7, lineHeight: '1.6', marginBottom: '24px' })} className={k?.mu}>
            Thank you, <strong>{submittedName}</strong>. Your application has been received and
            is now with the Vetting Panel for review.
          </p>
          <div style={sx({ ...infoBox, marginBottom: '16px', textAlign: 'left' })} className={k?.accBan} role="note">
            <p style={sx({ margin: 0, fontSize: '13px', opacity: 0.9, lineHeight: '1.6' })}>
              <strong>Follow your application on your candidate portal.</strong> A link to it is being sent by SMS
              to the phone number on your student record{nominationForm.collect_phone ? ' (the one you just gave us, if your record had none)' : ''} and may take a few minutes to arrive. Open it any time to
              see where your application stands and its outcome. If the link doesn't arrive, or you have no phone
              number on your student record, please contact the IT administrators.
            </p>
          </div>
          <div style={sx(infoBox)} className={k?.accBan}>
            <p style={sx({ margin: 0, fontSize: '13px', opacity: 0.8 })}>
              {approvalPolicyCopy}
            </p>
          </div>
          <button
            style={sx({ ...greenBtn, marginTop: '24px', width: '100%' })}
            className={k?.btn}
            onClick={() => {
              setSubmitted(false);
              setForm({ student_id: '', full_name: '', phone: '', position_id: '', manifesto: '', image: null });
              setPreview(null); setNominationFile(null); setNominationUploadId(''); setPaymentProof(null); setPaymentProofPreview(null); setPaymentMethod(''); uploadedRef.current.clear();
            }}
          >
            Submit Another Application
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={sx(outerWrap)} className="outer-wrap">
      <div style={sx({ maxWidth: '620px', margin: '0 auto', width: '100%' })} className={k?.apply}>

        {/* ── Header ── */}
        <div style={sx({ textAlign: 'center', marginBottom: '28px' })}>
          <h2 style={sx({ color: 'var(--text-color)', margin: '0 0 6px' })}>
            Apply for a Position
          </h2>
        </div>

        <ClosedNotice text={applicationsNoticeText(electionStatus)} />

        {/* Instructions for Applicants */}
        <div style={sx({ ...infoBox, marginBottom: '24px' })} className={k?.accBan}>
          <p style={sx({ margin: 0, fontSize: '13px', fontWeight: 'bold', marginBottom: '8px', opacity: 0.85 })}>
            Instructions for Applicants:
          </p>
          <ul style={sx({ margin: 0, paddingLeft: '18px', fontSize: '13px', opacity: 0.85, lineHeight: '1.9' })}>
            {nominationForm.enabled && <li><strong>Nomination Form:</strong> Download the blank form just below, complete and sign it, then upload the completed copy in the Upload Completed Form step further down.</li>}
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

          {/* ── Nomination Form (configured by superadmin) ──
              First card, straight under the instructions: the applicant downloads and signs it BEFORE filling in the form. */}
          {nominationForm.enabled && (
            <div style={sx(card)} className={k?.card}>
              <h4 style={sx(sectionTitle)} className={k?.sec}>{nominationForm.title || 'Nomination Form'}{nominationForm.required ? ' *' : ''}</h4>
              <div style={sx({ fontSize: '13px', lineHeight: 1.7, opacity: 0.8, marginBottom: 12, whiteSpace: 'pre-line' })} className={k?.mu}>
                {nominationForm.instructions || 'Download the blank form, complete and sign it, then upload the completed copy below.'}
              </div>
              {nominationForm.template_file?.url ? (
                <a href={nominationForm.template_file.download_url || nominationForm.template_file.url} download target="_blank" rel="noreferrer" style={sx({ ...greenBtn, display: 'inline-flex', alignItems: 'center', textDecoration: 'none', marginBottom: 14 })} className={k?.btn} data-track="apply-nomination-download">
                  Download blank form
                </a>
              ) : (
                <p style={sx({ fontSize: 12, opacity: 0.6, marginBottom: 14 })} className={k?.warnBan}>The blank form has not been uploaded yet. Contact the election administrator.</p>
              )}
            </div>
          )}


          {/* ── Personal details ── */}
          <div style={sx(card)} className={k?.card}>
            <h4 style={sx(sectionTitle)} className={k?.sec}>Personal Details</h4>

            <label style={sx(lbl)} className={k?.lbl} htmlFor={bp ? 'apply-student-id' : undefined}>{idText.label} *</label>
            <input
              id={bp ? 'apply-student-id' : undefined}
              data-field="student_id"
              aria-invalid={fieldErrors.student_id ? 'true' : undefined}
              style={sx({ ...inp, ...(fieldErrors.student_id ? invalidStyle : null) })}
              className={k?.in}
              placeholder={`e.g. ${idText.firstId}`}
              autoComplete="off"
              value={form.student_id}
              onChange={e => { clearField('student_id'); setForm(prev => ({ ...prev, student_id: e.target.value })); }}
            />
            {idText.hint && <p style={sx({ fontSize: 12, opacity: 0.65, margin: '6px 0 0' })} className={k?.mu}>{idText.hint}</p>}

            <label style={sx({ ...lbl, marginTop: '12px' })} className={k?.lbl} htmlFor={bp ? 'apply-full-name' : undefined}>Full Name (as on your student ID) *</label>
            <input
              id={bp ? 'apply-full-name' : undefined}
              data-field="full_name"
              aria-invalid={fieldErrors.full_name ? 'true' : undefined}
              style={sx({ ...inp, ...(fieldErrors.full_name ? invalidStyle : null) })}
              className={k?.in}
              placeholder={`e.g. ${idText.names[0]}`}
              value={form.full_name}
              onChange={e => { clearField('full_name'); setForm(prev => ({ ...prev, full_name: e.target.value })); }}
            />

            {nominationForm.collect_phone && (
              <>
                <label style={sx({ ...lbl, marginTop: '12px' })} className={k?.lbl} htmlFor={bp ? 'apply-phone' : undefined}>Phone number *</label>
                <input
                  id={bp ? 'apply-phone' : undefined}
                  data-field="phone"
                  type="tel" inputMode="tel" autoComplete="tel"
                  aria-invalid={fieldErrors.phone ? 'true' : undefined}
                  style={sx({ ...inp, ...(fieldErrors.phone ? invalidStyle : null) })}
                  className={k?.in}
                  placeholder="e.g. 0772 123456"
                  value={form.phone}
                  onChange={e => { clearField('phone'); setForm(prev => ({ ...prev, phone: e.target.value })); }}
                />
                <p style={sx({ fontSize: 12, opacity: 0.65, margin: '6px 0 0' })} className={k?.mu}>
                  If your student record has no phone number, we save this one to it. Your application status link is sent to the number on your record.
                </p>
              </>
            )}
          </div>

          {/* ── Position ── */}
          <div style={sx(card)} className={k?.card}>
            <h4 style={sx(sectionTitle)} className={k?.sec}>Position</h4>

            {posLoading ? (
              <LoadingBlock text="Loading available positions…" />
            ) : positions.length === 0 ? (
              <div style={sx({ ...infoBox, borderColor: 'color-mix(in srgb, var(--danger) 40%, transparent)' })} className={k?.alt}>
                <p style={sx({ margin: 0, color: 'var(--danger)', fontSize: '13px' })}>
                  No positions have been set up yet. Please check back later or contact the administration.
                </p>
              </div>
            ) : (
              <div data-field="position_id" tabIndex={-1} role="radiogroup" aria-label="Position"
                aria-invalid={fieldErrors.position_id ? 'true' : undefined}
                style={sx({ display: 'flex', flexDirection: 'column', gap: '10px', borderRadius: '10px', outline: 'none', ...(fieldErrors.position_id ? { boxShadow: '0 0 0 2px var(--danger)' } : null) })}>
                {positions.map((p, idx) => (
                  <div
                    key={p._id}
                    data-track={`apply-position-${idx + 1}`}
                    onClick={() => { if (uploading) return; clearField('position_id'); setForm(prev => ({ ...prev, position_id: p._id })); }}
                    className={k ? `${k.opt}${sel(form.position_id === p._id)}` : undefined}
                    style={sx({
                      ...positionOption,
                      border: form.position_id === p._id
                        ? '2px solid var(--success)'
                        : '1px solid var(--border-color)',
                      backgroundColor: form.position_id === p._id
                        ? 'color-mix(in srgb, var(--success) 10%, transparent)'
                        : 'var(--bg-color)',
                    })}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      {bp ? <bp.Tick on={form.position_id === p._id} /> : (
                      <div style={{
                        width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0,
                        border: form.position_id === p._id ? '2px solid var(--success)' : '2px solid var(--border-color)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {form.position_id === p._id && (
                          <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: 'var(--success)' }} />
                        )}
                      </div>
                      )}
                      <div>
                        <b style={{ color: 'var(--text-color)', fontSize: '14px' }}>{p.title}</b>
                        {p.description && (
                          <p style={sx({ margin: '2px 0 0', fontSize: '12px', opacity: 0.6 })} className={k?.mu}>{p.description}</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Manifesto ── */}
          <div style={sx(card)} className={k?.card}>
            <h4 id={bp ? 'apply-manifesto-h' : undefined} style={sx(sectionTitle)} className={k?.sec}>Your Manifesto *</h4>
            <p style={sx({ fontSize: '12px', opacity: 0.6, margin: '0 0 10px' })} className={k?.mu}>
              Briefly explain why you are running and what you plan to do if elected.
              Aim for 50–200 words.
            </p>
            <textarea
              data-field="manifesto"
              aria-labelledby={bp ? 'apply-manifesto-h' : undefined}
              aria-invalid={fieldErrors.manifesto ? 'true' : undefined}
              style={sx({ ...inp, height: '120px', resize: 'vertical', ...(fieldErrors.manifesto ? invalidStyle : null) })}
              className={k?.ta}
              placeholder="I am running because…"
              value={form.manifesto}
              maxLength={MANIFESTO_MAX_CHARS}
              onChange={e => { clearField('manifesto'); setForm(prev => ({ ...prev, manifesto: e.target.value })); }}
            />
            <small
              className={k ? `${k.count}${form.manifesto.length >= MANIFESTO_MAX_CHARS ? ` ${k.lim}` : ''}` : undefined}
              style={sx({ opacity: form.manifesto.length > MANIFESTO_MAX_CHARS * 0.9 ? 1 : 0.4, fontSize: '11px', color: form.manifesto.length >= MANIFESTO_MAX_CHARS ? 'var(--warning)' : undefined })}>
              {form.manifesto.trim().split(/\s+/).filter(Boolean).length} words · {form.manifesto.length}/{MANIFESTO_MAX_CHARS} characters
            </small>
          </div>

          {/* ── Nomination Form: upload (the download sits at the top, under the instructions) ── */}
          {nominationForm.enabled && (
            <div style={sx(card)} className={k?.card}>
              <h4 style={sx(sectionTitle)} className={k?.sec}>Upload Completed Form{nominationForm.required ? ' *' : ''}</h4>
              <label style={sx(lbl)} className={k?.lbl}>Completed form ({(nominationForm.accepted_types || ['pdf']).join(' / ').toUpperCase()}) {nominationForm.required ? '*' : '(optional)'}</label>
              {draftRestored && !nominationFile && nominationForm.required && <p role="note" className={k?.warnBan} style={sx({ margin: '0 0 8px', fontSize: 12, color: 'var(--warning)', fontWeight: 600 })}>Re-attach your signed nomination form. Files cannot be restored from a saved draft.</p>}
              <label data-track="apply-nomination-upload" data-field="nomination_form" tabIndex={-1} aria-invalid={fieldErrors.nomination_form ? 'true' : undefined}
                className={k?.upload} style={sx({ ...photoUploadArea, minHeight: 100, ...(fieldErrors.nomination_form ? { border: '2px dashed var(--danger)' } : null) })}>
                <div style={sx({ textAlign: 'center', opacity: 0.6 })} className={k?.upEmpty}>
                  <div style={{ fontSize: 30, marginBottom: 6 }}><Icon name="file" /></div>
                  <span style={{ fontSize: 13 }}>{nominationFile ? nominationFile.name : 'Click to upload your completed form'}</span>
                  <br /><span style={sx({ fontSize: 11, opacity: .7 })}>{(nominationForm.accepted_types || ['pdf']).map(x=>x.toUpperCase()).join(', ')} · up to {nominationForm.max_mb || 5} MB</span>
                </div>
                <input type="file" accept={(nominationForm.accepted_types || ['pdf']).map(x=>`.${x}`).join(',')} style={{ display: 'none' }}
                  onChange={handleNominationChange} />
              </label>
              {nominationFile && <button type="button" style={sx({ ...ghostBtn, marginTop: 8, fontSize: 12, color: 'var(--danger)' })} className={k?.del}
                onClick={() => { setNominationFile(null); setNominationUploadId(''); clearField('nomination_form'); }}>Remove nomination form</button>}
            </div>
          )}

          {/* ── Payment Proof ── */}
          <div style={sx(card)} className={k?.card}>
            <h4 style={sx(sectionTitle)} className={k?.sec}>Proof of Payment *</h4>
            <p style={sx({ fontSize: '12px', opacity: 0.6, margin: '0 0 14px' })} className={k?.mu}>
              Select your payment method and upload a screenshot or photo of the payment receipt.
            </p>

            {/* Fee for the chosen position + disclaimer */}
            {!selectedPosition ? (
              <div style={sx({ ...infoBox, marginBottom: '16px' })} className={k?.accBan}>
                <p style={sx({ margin: 0, fontSize: '13px', opacity: 0.8 })}>
                  Select a position above to see the nomination fee you must pay, or{' '}
                  <button type="button" data-track="apply-fee-link" onClick={openFees} style={sx(linkBtn)} className={k?.inl}>check every position's fee first</button>.
                </p>
              </div>
            ) : requiredFee > 0 ? (
              <div style={sx({ ...infoBox, marginBottom: '16px', borderColor: 'var(--success)' })} className={k?.ban} role="note">
                <p style={sx({ margin: 0, fontSize: '13px', lineHeight: 1.7, opacity: 0.85 })}>Nomination fee for <strong>{selectedPosition.title}</strong></p>
                <p style={sx({ margin: '6px 0 12px', display: 'inline-block', padding: '4px 14px', borderRadius: 10, fontSize: '30px', lineHeight: '40px', fontWeight: 800, color: 'var(--text-color)', background: 'var(--bp-tint, var(--surface-2))', border: '1px solid var(--bp-ac-edge, var(--border-color))' })} className={k?.fee}>
                  UGX {requiredFee.toLocaleString('en-UG')}
                </p>
                <MobileMoneyNumber info={paymentInfo} style={{ margin: '0 0 10px' }} />
                <p style={sx({ margin: 0, fontSize: '13px', lineHeight: 1.7, opacity: 0.85 })}>
                  <strong>Important:</strong> your receipt must show a payment of this full amount. Applications with
                  an incomplete or incorrect payment amount will be rejected.
                </p>
                <button type="button" data-track="apply-fee-link" onClick={openFees} style={sx({ ...linkBtn, display: 'block', marginTop: '8px', fontSize: '13px' })} className={k?.inl}>
                  See fees for other positions
                </button>
              </div>
            ) : null}
          
            {/* Payment method selector */}
            <label style={sx(lbl)} className={k?.lbl}>Payment Method *</label>
            <div data-field="payment_method" tabIndex={-1} role="radiogroup" aria-label="Payment method"
              aria-invalid={fieldErrors.payment_method ? 'true' : undefined}
              style={sx({ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px', borderRadius: '10px', outline: 'none', ...(fieldErrors.payment_method ? { boxShadow: '0 0 0 2px var(--danger)' } : null) })}>
              {['Mobile Money (MTN)', 'Mobile Money (Airtel)', 'Bank Transfer', 'Cash Receipt'].map(method => (
                <div
                  key={method}
                  data-track="apply-payment-method"
                  onClick={() => { if (uploading) return; clearField('payment_method'); setPaymentMethod(method); }}
                  className={k ? `${k.opt}${sel(paymentMethod === method)}` : undefined}
                  style={sx({
                    ...positionOption,
                    border: paymentMethod === method
                      ? '2px solid var(--success)'
                      : '1px solid var(--border-color)',
                    backgroundColor: paymentMethod === method
                      ? 'color-mix(in srgb, var(--success) 10%, transparent)'
                      : 'var(--bg-color)',
                  })}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {bp ? <bp.Tick on={paymentMethod === method} /> : (
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
                    )}
                    <span style={{ color: 'var(--text-color)', fontSize: '14px' }}>{method}</span>
                  </div>
                </div>
              ))}
            </div>
          
            {/* Proof upload */}
            <label style={sx(lbl)} className={k?.lbl}>Payment Receipt / Screenshot *</label>
            {draftRestored && !paymentProof && (
              <p role="note" className={k?.warnBan} style={sx({ margin: '0 0 8px', fontSize: '12px', color: 'var(--warning)', fontWeight: 600 })}>
                Re-attach your receipt. Your typed answers were restored, but files cannot be saved.
              </p>
            )}
            <label data-track="apply-proof-upload" data-field="payment_proof" tabIndex={-1} aria-invalid={fieldErrors.payment_proof ? 'true' : undefined}
              className={k?.upload}
              style={sx({ ...photoUploadArea, minHeight: '120px', ...(fieldErrors.payment_proof ? { border: '2px dashed var(--danger)' } : null) })}>
              {paymentProofPreview ? (
                <img src={paymentProofPreview} alt="Payment proof preview" className="panel-fade-in"
                  style={{ maxWidth: '100%', maxHeight: '200px', objectFit: 'contain', borderRadius: '8px' }} />
              ) : (
                <div style={sx({ textAlign: 'center', opacity: 0.5 })} className={k?.upEmpty}>
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}><Icon name="receipt" /></div>
                  <span style={{ fontSize: '13px' }}>Click to upload receipt or screenshot</span>
                  <br />
                  <span style={sx({ fontSize: '11px', opacity: 0.7 })}>JPG, PNG, WEBP or GIF, up to 5 MB</span>
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
                style={sx({ ...ghostBtn, marginTop: '8px', fontSize: '12px', color: 'var(--danger)' })}
                className={k?.del}
                onClick={() => { setPaymentProofPreview(null); setPaymentProof(null); }}
              >
                Remove receipt
              </button>
            )}
          </div>
          
          {/* ── Photo ── */}
          <div style={sx(card)} className={k?.card}>
            <h4 style={sx(sectionTitle)} className={k?.sec}>Passport Photo (optional)</h4>
            <p style={sx({ fontSize: '12px', opacity: 0.6, margin: '0 0 12px' })} className={k?.mu}>
              A clear headshot. This will appear on the ballot paper if approved.
            </p>
            <label style={sx(photoUploadArea)} className={k?.upload}>
              {preview ? (
                <img src={preview} alt="Preview" className="panel-fade-in" style={photoPreview} />
              ) : (
                <div style={sx({ textAlign: 'center', opacity: 0.5 })} className={k?.upEmpty}>
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
                style={sx({ ...ghostBtn, marginTop: '8px', fontSize: '12px', color: 'var(--danger)' })}
                className={k?.del}
                onClick={() => { setPreview(null); setForm(prev => ({ ...prev, image: null })); }}
              >
                Remove photo
              </button>
            )}
          </div>

          </fieldset>

          {/* ── Error ── */}
          {error && (
            <div style={sx(errorBox)} className={k?.alt} role="alert">
              <Icon name="warning" /> {error}
            </div>
          )}

          {/* ── Declaration + submit ── */}
          <div style={sx(card)} className={k?.card}>
            <div style={sx({ ...infoBox, marginBottom: '16px' })} className={k?.accBan}>
              <p style={sx({ margin: 0, fontSize: '12px', opacity: 0.8, lineHeight: '1.6' })}>
                By submitting this form I confirm that the information provided is accurate,
                I consent to my details being reviewed by the Election Commission.
              </p>
            </div>
            {bp && uploading && <bp.StepBar step={step || 1} of={form.image ? (nominationForm.enabled ? 5 : 4) : (nominationForm.enabled ? 4 : 3)} />}
            <button
              type="submit"
              data-track="apply-submit"
              style={sx({ ...greenBtn, width: '100%', padding: '14px', fontSize: '15px' })}
              className={k?.btn}
              disabled={uploading || positions.length === 0}
              aria-busy={uploading}
            >
              {uploading
                ? <><Icon name="loading" /> {stepLabel(step || 1, Boolean(form.image), Boolean(nominationForm.enabled))}{uploadPct != null ? ` ${uploadPct}%` : ''}</>
                : "Submit Application"}
            </button>
            {uploading && (
              <div role="status" style={sx({ marginTop: '10px', fontSize: '12px', textAlign: 'center' })} className={k?.stat}>
                {slow && <p className={k?.warnBan} style={sx({ margin: '0 0 8px', color: 'var(--warning)', fontWeight: 600 })}>Slow connection. Keep this page open; it can take a minute.</p>}
                <button type="button" onClick={cancelSubmit} style={sx(ghostBtn)} className={k?.sm}>Cancel</button>
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
const btn           = { padding: '10px 18px', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', color: 'var(--bp-ai, #fff)' };
const greenBtn      = { ...btn, backgroundColor: 'var(--success)' };
const ghostBtn      = { padding: '8px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
