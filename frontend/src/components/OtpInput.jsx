import React, { useState, useEffect, useRef } from 'react';

export default function OtpInput({ otp, setOtp, onVerify, onBack, phoneNumber }) {
  const [isLocked, setIsLocked] = useState(false);
  const [hasError, setHasError] = useState(false);
  const inputRef = useRef(null);

  // Auto-focus the input for a better experience
  useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
  }, []);

  const handleVerify = async () => {
    setHasError(false); // Reset error state on new attempt
    try {
      await onVerify();
    } catch (err) {
      // 1. STRICT LOGIC: Only lock out if the Backend sends a 403.
      if (err.status === 403 || (err.response && err.response.status === 403)) {
        setIsLocked(true);
      } else {
        // 2. RELAXED LOGIC: For typos (400 errors), just show a warning.
        setHasError(true);
        setOtp(""); 
        if (inputRef.current) inputRef.current.focus();
      }
    }
  };

  if (isLocked) {
    return (
      <div style={{ textAlign: 'center', color: '#fff', padding: '20px' }}>
        <div style={{ fontSize: '50px', marginBottom: '20px' }}>🔒</div>
        <h2 style={{ fontSize: '20px', color: '#e74c3c', fontWeight: 'bold' }}>Access Restricted</h2>
        <p style={{ color: '#cbd5e1', marginTop: '10px', lineHeight: '1.5' }}>
          Too many OTP requests detected. <br />
          Please contact the administrator to verify your identity.
        </p>
        
        <a 
          href="https://wa.me/25672707723?text=Hello%20Admin,%20my%20OTP%20access%20is%20restricted%20on%20the%20Election%20Portal."
          target="_blank"
          rel="noopener noreferrer"
          style={{ 
            display: 'block', 
            marginTop: '15px', 
            color: '#2ecc71', 
            fontWeight: 'bold', 
            textDecoration: 'none' 
          }}
        >
          💬 Contact Admin via WhatsApp
        </a>

        <button onClick={onBack} style={{ ...secondaryBtnStyle, marginTop: '20px' }}>Return to Login</button>
      </div>
    );
  }

  return (
    <div style={{ textAlign: 'center', color: '#fff' }}>
      <h2 style={{ fontSize: '18px', marginBottom: '20px', fontWeight: '500' }}>
        Confirm the code sent to <span style={{ color: '#2ecc71' }}>{phoneNumber}</span>
      </h2>
      
      <input
        ref={inputRef}
        type="text"
        inputMode="numeric"
        maxLength="6"
        value={otp}
        placeholder="· · · · · ·"
        onChange={(e) => {
          setHasError(false);
          setOtp(e.target.value.replace(/\D/g, ''));
        }}
        style={{ 
          fontSize: '32px', 
          width: '220px', 
          textAlign: 'center', 
          padding: '12px', 
          backgroundColor: '#0f172a',
          border: hasError ? '2px solid #e74c3c' : '2px solid #334155',
          borderRadius: '12px',
          color: '#fff',
          letterSpacing: '8px',
          outline: 'none'
        }}
      />

      {hasError && (
        <p style={{ color: '#e74c3c', fontSize: '14px', marginTop: '10px' }}>
          Incorrect code. Please check your SMS and try again.
        </p>
      )}

      <div style={{ marginTop: '30px', display: 'flex', gap: '15px', justifyContent: 'center' }}>
        <button onClick={onBack} style={secondaryBtnStyle}>Back</button>
        <button 
          onClick={handleVerify} 
          disabled={otp.length < 6}
          style={{ 
            backgroundColor: otp.length < 6 ? '#1e293b' : '#2ecc71', 
            color: 'white', 
            padding: '12px 30px', 
            border: 'none', 
            borderRadius: '8px', 
            fontWeight: 'bold', 
            cursor: otp.length < 6 ? 'default' : 'pointer' 
          }}
        >
          Verify Account
        </button>
      </div>
    </div>
  );
}

const secondaryBtnStyle = { 
  padding: '12px 25px', 
  borderRadius: '8px', 
  border: '1px solid #334155', 
  background: 'transparent', 
  color: '#fff', 
  cursor: 'pointer' 
};
