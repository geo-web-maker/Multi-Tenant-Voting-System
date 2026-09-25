import React, { useEffect, useState } from 'react';
import api from '../api';
import { Icon } from './icons.jsx';
import ClosedNotice, { applicationsNoticeText } from './ClosedNotice';
import { loadDraft, saveDraft, clearDraft } from '../session';
import usePolling from '../hooks/usePolling';
import { useHelpMenu } from '../context/HelpMenuContext';

// Signed, server-side upload via our own backend — replaces the old
// unsigned Cloudinary preset upload that ran straight from the browser.
// This is the one upload endpoint that has to stay public (applicants
// aren't logged in), but the backend still validates file type/size and
// rate-limits per IP, and the Cloudinary secret never touches the client.
async function uploadToCloudinary(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post('/apply/upload-image', formData);
  return res.data.secure_url;
}

// Keep in sync with MANIFESTO_MAX_CHARS in backend/main.py.
const MANIFESTO_MAX_CHARS = 3000;

export default function ApplicantPortal() {
  const { openFees } = useHelpMenu();

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
  const [uploadingProof, setUploadingProof] = useState(false);

  useEffect(() => {
    api.get('/positions')
      .then(res => {
        setPositions(res.data);
        // A restored draft may point at a position that has since been removed.
        setForm(prev => (
          prev.position_id && !res.data.some(p => p._id === prev.position_id)
            ? { ...prev, position_id: '' }
            : prev
        ));
      })
      .catch(() => setPositions([]))
      .finally(() => setPosLoading(false));
    api.get('/election-status')
      .then(res => { setApprovalPolicy(res.data.approval_policy || 'majority_total'); setElectionStatus(res.data); })
      .catch(() => {});
  }, []);

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
    unanimous: 'Every commissioner must agree — unanimous approval required.',
    majority_total: 'The commission reviews all applications before any candidate appears on the ballot. A majority of the commission must agree for approval.',
    majority_cast: 'The commission reviews all applications before any candidate appears on the ballot. Resolves once every commissioner has voted — whichever side has more wins.',
  }[approvalPolicy] || 'The commission reviews all applications before any candidate appears on the ballot.';

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

  const handlePhotoChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setForm(prev => ({ ...prev, image: file }));
    setPreview(URL.createObjectURL(file));
  };

  const handlePaymentProofChange = (e) => {
  const file = e.target.files[0];
  if (!file) return;
  setPaymentProof(file);
  setPaymentProofPreview(URL.createObjectURL(file));
  };
  
const handleSubmit = async (e) => {
  e.preventDefault();
  setError('');

if (!form.student_id.trim())  { setError('Student ID is required.');    return; }
  if (!form.full_name.trim())   { setError('Full name is required.');      return; }
  if (!form.position_id)        { setError('Please select a position.');   return; }
  if (!form.manifesto.trim())   { setError('Manifesto cannot be empty.');  return; }
  if (!paymentMethod) { setError('Please select a payment method.'); return; }
  if (!paymentProof)  { setError('Please upload proof of payment.'); return; }

  setUploading(true);
  try {
    // Gate: confirm this student_id + name is actually on the voter register
    // BEFORE spending any Cloudinary uploads on photo/payment proof.
    try {
      await api.post('/apply/check-eligibility', {
        student_id: form.student_id.trim(),
        full_name:  form.full_name.trim(),
      });
    } catch (eligErr) {
      setError(eligErr.response?.data?.detail || 'Could not verify your details. Please check your Student ID and name.');
      setUploading(false);
      return;
    }

    let image_url = '';
    if (form.image) {
      image_url = await uploadToCloudinary(form.image);
    }

    setUploadingProof(true);
    let payment_proof_url = '';
    if (paymentProof) {
      payment_proof_url = await uploadToCloudinary(paymentProof);
    }
    setUploadingProof(false);

    await api.post(`/apply`, {
      student_id:        form.student_id.trim(),
      full_name:         form.full_name.trim(),
      position_id:       form.position_id,
      manifesto:         form.manifesto.trim(),
      image_url,
      payment_method:    paymentMethod,
      payment_proof_url,
    });

    setSubmittedName(form.full_name.trim());
    setSubmitted(true);
  } catch (err) {       
    if (err.response?.status === 403 && /closed|not opened|has ended/i.test(String(err.response?.data?.detail || ''))) {
      api.get('/election-status').then(r => setElectionStatus(r.data)).catch(() => {});
    }
    const d = err.response?.data?.detail;
    setError(typeof d === 'string' ? d
      : Array.isArray(d) ? d.map(x => x.msg).filter(Boolean).join(' ') || 'Please check your entries and try again.'
      : 'Submission failed. Please try again.');
  } finally {
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
            is now pending review by the Election Commission. You will be notified of the outcome.
          </p>
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

        {/* ── How it works ── */}
        <div style={{ ...infoBox, marginBottom: '24px' }}>
          <p style={{ margin: 0, fontSize: '13px', opacity: 0.85, lineHeight: '1.7' }}>
            <strong>How it works:</strong> Fill in the form below and submit your application.
            The Election Commission will review it — <em>all commissioners must unanimously approve</em> before
            your name appears on the ballot.
          </p>
        </div>

        <form onSubmit={handleSubmit} style={formCol}>

          {/* ── Personal details ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Personal Details</h4>

            <label style={lbl}>Student Registration Number *</label>
            <input
              style={inp}
              placeholder="e.g. 22/U/IED/1086/GV"
              value={form.student_id}
              onChange={e => setForm(prev => ({ ...prev, student_id: e.target.value }))}
            />

            <label style={{ ...lbl, marginTop: '12px' }}>Full Name (as on your student ID) *</label>
            <input
              style={inp}
              placeholder="e.g. Ayebale Elizabeth"
              value={form.full_name}
              onChange={e => setForm(prev => ({ ...prev, full_name: e.target.value }))}
            />
          </div>

          {/* ── Position ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Position</h4>

            {posLoading ? (
              <p style={{ opacity: 0.5, fontSize: '13px' }}>Loading available positions…</p>
            ) : positions.length === 0 ? (
              <div style={{ ...infoBox, borderColor: 'color-mix(in srgb, var(--danger) 40%, transparent)' }}>
                <p style={{ margin: 0, color: 'var(--danger)', fontSize: '13px' }}>
                  No positions have been set up yet. Please check back later or contact the administration.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {positions.map(p => (
                  <div
                    key={p._id}
                    onClick={() => setForm(prev => ({ ...prev, position_id: p._id }))}
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
              style={{ ...inp, height: '120px', resize: 'vertical' }}
              placeholder="I am running because…"
              value={form.manifesto}
              maxLength={MANIFESTO_MAX_CHARS}
              onChange={e => setForm(prev => ({ ...prev, manifesto: e.target.value }))}
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
                  <button type="button" onClick={openFees} style={linkBtn}>check every position's fee first</button>.
                </p>
              </div>
            ) : requiredFee > 0 ? (
              <div style={{ ...infoBox, marginBottom: '16px', borderColor: 'var(--success)' }} role="note">
                <p style={{ margin: 0, fontSize: '13px', opacity: 0.85 }}>Nomination fee for <strong>{selectedPosition.title}</strong></p>
                <p style={{ margin: '4px 0 8px', fontSize: '22px', fontWeight: 700, color: 'var(--text-color)' }}>
                  UGX {requiredFee.toLocaleString('en-UG')}
                </p>
                <p style={{ margin: 0, fontSize: '12px', lineHeight: 1.6, opacity: 0.85 }}>
                  <strong>Important:</strong> your receipt must show a payment of this full amount. Applications with
                  an incomplete or incorrect payment amount will be rejected.
                </p>
                <button type="button" onClick={openFees} style={{ ...linkBtn, display: 'block', marginTop: '8px' }}>
                  See fees for other positions
                </button>
              </div>
            ) : null}
          
            {/* Payment method selector */}
            <label style={lbl}>Payment Method *</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
              {['Mobile Money (MTN)', 'Mobile Money (Airtel)', 'Bank Transfer', 'Cash Receipt'].map(method => (
                <div
                  key={method}
                  onClick={() => setPaymentMethod(method)}
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
            <label style={{ ...photoUploadArea, minHeight: '120px' }}>
              {paymentProofPreview ? (
                <img src={paymentProofPreview} alt="Payment proof preview"
                  style={{ maxWidth: '100%', maxHeight: '200px', objectFit: 'contain', borderRadius: '8px' }} />
              ) : (
                <div style={{ textAlign: 'center', opacity: 0.5 }}>
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}><Icon name="receipt" /></div>
                  <span style={{ fontSize: '13px' }}>Click to upload receipt or screenshot</span>
                  <br />
                  <span style={{ fontSize: '11px', opacity: 0.7 }}>JPG, PNG, PDF accepted</span>
                </div>
              )}
              <input
                type="file"
                accept="image/*,application/pdf"
                style={{ display: 'none' }}
                onChange={handlePaymentProofChange}
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
                <img src={preview} alt="Preview" style={photoPreview} />
              ) : (
                <div style={{ textAlign: 'center', opacity: 0.5 }}>
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}><Icon name="camera" /></div>
                  <span style={{ fontSize: '13px' }}>Click to upload photo</span>
                </div>
              )}
              <input
                type="file"
                accept="image/*"
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

          {/* ── Error ── */}
          {error && (
            <div style={errorBox}>
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
              style={{ ...greenBtn, width: '100%', padding: '14px', fontSize: '15px' }}
              disabled={uploading || positions.length === 0}
            >
              {uploadingProof ? <><Icon name="loading" /> Uploading receipt…</> : uploading ? <><Icon name="loading" /> Submitting…</> : "Submit Application"}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}

// ── Styles ──
const outerWrap     = { width: '100%', minHeight: '100vh', backgroundColor: 'var(--bg-color)', padding: '24px 16px' };
const card          = { padding: '20px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--card-bg)', marginBottom: '16px' };
const formCol       = { display: 'flex', flexDirection: 'column', gap: '0px' };
const sectionTitle  = { margin: '0 0 14px', color: 'var(--text-color)', fontSize: '14px', fontWeight: '700' };
const lbl           = { display: 'block', fontSize: '12px', opacity: 0.65, marginBottom: '6px', fontWeight: '600' };
const inp           = { padding: '11px 13px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-color)', color: 'var(--text-color)', fontSize: '14px', width: '100%', boxSizing: 'border-box' };
const positionOption = { padding: '14px', borderRadius: '10px', cursor: 'pointer', transition: 'all 0.15s' };
const infoBox     = { padding: '12px 16px', backgroundColor: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--info) 30%, transparent)' };
const linkBtn     = { background: 'none', border: 'none', padding: 0, margin: 0, font: 'inherit', fontWeight: 700, color: 'var(--success)', textDecoration: 'underline', cursor: 'pointer' };
const errorBox    = { padding: '10px 14px', backgroundColor: 'color-mix(in srgb, var(--danger) 15%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--danger) 40%, transparent)', color: 'var(--danger)', fontSize: '12px', fontWeight: '600', marginTop: '10px' };
const photoUploadArea = { display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px dashed var(--border-color)', borderRadius: '10px', padding: '20px', cursor: 'pointer', minHeight: '100px' };
const photoPreview  = { width: '100px', height: '100px', objectFit: 'cover', borderRadius: '8px' };
const btn           = { padding: '10px 18px', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', color: '#fff' };
const greenBtn      = { ...btn, backgroundColor: 'var(--success)' };
const ghostBtn      = { padding: '8px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
