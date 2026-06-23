import React, { useEffect, useState } from 'react';
import axios from 'axios';

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

export default function ApplicantPortal({ apiBase }) {
  const API_URL = apiBase.replace(/\/$/, '');

  const [positions, setPositions]   = useState([]);
  const [posLoading, setPosLoading] = useState(true);
  const [uploading, setUploading]   = useState(false);
  const [submitted, setSubmitted]   = useState(false);
  const [submittedName, setSubmittedName] = useState('');
  const [error, setError]           = useState('');

  const [form, setForm] = useState({
    student_id:  '',
    full_name:   '',
    position_id: '',
    manifesto:   '',
    image:       null,
  });

  const [preview, setPreview] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState('');
  const [paymentProof, setPaymentProof] = useState(null);
  const [paymentProofPreview, setPaymentProofPreview] = useState(null);
  const [uploadingProof, setUploadingProof] = useState(false);

  useEffect(() => {
    axios.get(`${API_URL}/positions`)
      .then(res => setPositions(res.data))
      .catch(() => setPositions([]))
      .finally(() => setPosLoading(false));
  }, []);

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

    setUploading(true);
      if (!paymentMethod) { setError('Please select a payment method.'); return; }
      if (!paymentProof)  { setError('Please upload proof of payment.'); return; }
      
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
      
      await axios.post(`${API_URL}/apply`, {
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
      setError(err.response?.data?.detail || 'Submission failed. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  // ── Success screen ──
  if (submitted) {
    return (
      <div style={outerWrap}>
        <div style={{ ...card, textAlign: 'center', maxWidth: '480px', margin: '0 auto' }}>
          <div style={{ fontSize: '54px', marginBottom: '16px' }}>🎉</div>
          <h2 style={{ color: 'var(--text-color)', margin: '0 0 10px' }}>Application Submitted!</h2>
          <p style={{ opacity: 0.7, lineHeight: '1.6', marginBottom: '24px' }}>
            Thank you, <strong>{submittedName}</strong>. Your application has been received and
            is now pending review by the Election Commission. You will be notified of the outcome.
          </p>
          <div style={infoBox}>
            <p style={{ margin: 0, fontSize: '13px', opacity: 0.8 }}>
              📋 The commission reviews all applications before any candidate appears on the ballot.
              Full consensus from all commissioners is required for approval.
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
    <div style={outerWrap}>
      <div style={{ maxWidth: '620px', margin: '0 auto', width: '100%' }}>

        {/* ── Header ── */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <h2 style={{ color: 'var(--text-color)', margin: '0 0 6px' }}>
            🏅 Apply for a Position
          </h2>
          <p style={{ opacity: 0.6, fontSize: '14px', margin: 0 }}>
            KYAMBOGO COORDINATORS UNION — KYUCCU 2026 Elections
          </p>
        </div>

        {/* ── How it works ── */}
        <div style={{ ...infoBox, marginBottom: '24px' }}>
          <p style={{ margin: 0, fontSize: '13px', opacity: 0.85, lineHeight: '1.7' }}>
            <strong>How it works:</strong> Fill in the form below and submit your application.
            The Election Commission will review it — <em>all commissioners must unanimously approve</em> before
            your name appears on the ballot. The superadmin may also approve or deny at any time.
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
              <div style={{ ...infoBox, borderColor: '#e74c3c40' }}>
                <p style={{ margin: 0, color: '#e74c3c', fontSize: '13px' }}>
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
                        ? '2px solid #2ecc71'
                        : '1px solid var(--border-color)',
                      backgroundColor: form.position_id === p._id
                        ? '#2ecc7110'
                        : 'var(--bg-color)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0,
                        border: form.position_id === p._id ? '2px solid #2ecc71' : '2px solid var(--border-color)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {form.position_id === p._id && (
                          <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#2ecc71' }} />
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
              onChange={e => setForm(prev => ({ ...prev, manifesto: e.target.value }))}
            />
            <small style={{ opacity: 0.4, fontSize: '11px' }}>
              {form.manifesto.trim().split(/\s+/).filter(Boolean).length} words
            </small>
          </div>

          {/* ── Payment Proof ── */}
          <div style={card}>
            <h4 style={sectionTitle}>Proof of Payment *</h4>
            <p style={{ fontSize: '12px', opacity: 0.6, margin: '0 0 14px' }}>
              Select your payment method and upload a screenshot or photo of the payment receipt.
            </p>
          
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
                      ? '2px solid #2ecc71'
                      : '1px solid var(--border-color)',
                    backgroundColor: paymentMethod === method
                      ? '#2ecc7110'
                      : 'var(--bg-color)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      width: '20px', height: '20px', borderRadius: '50%', flexShrink: 0,
                      border: paymentMethod === method
                        ? '2px solid #2ecc71'
                        : '2px solid var(--border-color)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {paymentMethod === method && (
                        <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#2ecc71' }} />
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
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}>🧾</div>
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
                style={{ ...ghostBtn, marginTop: '8px', fontSize: '12px', color: '#e74c3c' }}
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
                  <div style={{ fontSize: '32px', marginBottom: '6px' }}>📷</div>
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
                style={{ ...ghostBtn, marginTop: '8px', fontSize: '12px', color: '#e74c3c' }}
                onClick={() => { setPreview(null); setForm(prev => ({ ...prev, image: null })); }}
              >
                Remove photo
              </button>
            )}
          </div>

          {/* ── Error ── */}
          {error && (
            <div style={errorBox}>
              ⚠️ {error}
            </div>
          )}

          {/* ── Declaration + submit ── */}
          <div style={card}>
            <div style={{ ...infoBox, marginBottom: '16px' }}>
              <p style={{ margin: 0, fontSize: '12px', opacity: 0.8, lineHeight: '1.6' }}>
                By submitting this form I confirm that the information provided is accurate,
                I am a registered student of Kyambogo University, and I consent to my details
                being reviewed by the Election Commission.
              </p>
            </div>
            <button
              type="submit"
              style={{ ...greenBtn, width: '100%', padding: '14px', fontSize: '15px' }}
              disabled={uploading || positions.length === 0}
            >
              {uploadingProof ? '⏳ Uploading receipt…' : uploading ? '⏳ Submitting…' : '📨 Submit Application'}
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
const infoBox       = { padding: '12px 16px', backgroundColor: '#3498db10', borderRadius: '8px', border: '1px solid #3498db30' };
const errorBox      = { padding: '12px 16px', backgroundColor: '#e74c3c15', borderRadius: '8px', border: '1px solid #e74c3c40', color: '#e74c3c', fontSize: '13px', fontWeight: '600' };
const photoUploadArea = { display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px dashed var(--border-color)', borderRadius: '10px', padding: '20px', cursor: 'pointer', minHeight: '100px' };
const photoPreview  = { width: '100px', height: '100px', objectFit: 'cover', borderRadius: '8px' };
const btn           = { padding: '10px 18px', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', color: '#fff' };
const greenBtn      = { ...btn, backgroundColor: '#2ecc71' };
const ghostBtn      = { padding: '8px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
