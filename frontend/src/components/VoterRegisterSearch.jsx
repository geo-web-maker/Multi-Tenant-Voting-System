import React, { useState, useEffect, useRef } from 'react';
import api from '../api';

export default function VoterRegisterSearch() {
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [checkId, setCheckId] = useState('');
  const [checkName, setCheckName] = useState('');
  const [checkResult, setCheckResult] = useState(null);
  const [checkError, setCheckError] = useState('');
  const [checking, setChecking] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    setLoading(true);
    debounceRef.current = setTimeout(() => {
      api.get('/voter-register', { params: { q, page } })
        .then(res => { setResults(res.data.results); setTotal(res.data.total); })
        .catch(() => { setResults([]); setTotal(0); })
        .finally(() => setLoading(false));
    }, 400);
    return () => clearTimeout(debounceRef.current);
  }, [q, page]);

  const checkNumber = () => {
    setCheckError(''); setCheckResult(null); setChecking(true);
    api.post('/voter-register/check-number', { student_id: checkId, full_name: checkName })
      .then(res => setCheckResult(res.data))
      .catch(err => setCheckError(err.response?.data?.detail || 'Something went wrong.'))
      .finally(() => setChecking(false));
  };

  const pageCount = Math.ceil(total / 25) || 1;

  return (
    <div style={wrapStyle}>
      <div style={colStyle}>
        <h3 style={headingStyle}>🔍 Voter Register</h3>
        <p style={subStyle}>Search by name or registration number to confirm your record.</p>
        <input
          placeholder="e.g. Namusoke or 23/U/BCS/10245/GV"
          value={q}
          onChange={e => { setQ(e.target.value); setPage(1); }}
          style={registerInputStyle}
        />
        <div style={tableWrapStyle}>
          <div style={tableHeaderStyle}>
            <span>Name</span>
            <span>Reg. Number</span>
          </div>
          <div style={tableBodyStyle}>
            {loading && <p style={mutedCenter}>Searching…</p>}
            {!loading && results.length === 0 && <p style={mutedCenter}>No matches found.</p>}
            {!loading && results.map((v, i) => (
              <div key={i} style={rowStyle}>
                <span style={{ fontWeight: 600 }}>{v.full_name}</span>
                <span style={{ opacity: 0.75, fontFamily: 'monospace', fontSize: '13px' }}>{v.student_id}</span>
              </div>
            ))}
          </div>
        </div>
        {total > 25 && (
          <div style={pagerStyle}>
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} style={pagerBtnStyle}>← Prev</button>
            <span style={{ opacity: 0.8, fontSize: '13px' }}>Page {page} of {pageCount}</span>
            <button disabled={page >= pageCount} onClick={() => setPage(p => p + 1)} style={pagerBtnStyle}>Next →</button>
          </div>
        )}
      </div>

      <div style={colStyle}>
        <h3 style={headingStyle}>📱 Check My Number</h3>
        <p style={subStyle}>Confirm the phone number we have on file is still yours.</p>
        <input placeholder="Registration Number" value={checkId} onChange={e => setCheckId(e.target.value)} style={registerInputStyle} />
        <input placeholder="Full Name" value={checkName} onChange={e => setCheckName(e.target.value)} style={registerInputStyle} />
        <button onClick={checkNumber} disabled={checking || !checkId || !checkName} style={checkBtnStyle(checking)}>
          {checking ? 'Checking…' : 'Check Number'}
        </button>
        {checkError && <p style={errorTextStyle}>{checkError}</p>}
        {checkResult && (
          <div style={resultBoxStyle(checkResult.phone_on_file)}>
            {checkResult.phone_on_file
              ? <>✅ Number on file: <strong>{checkResult.masked_phone}</strong></>
              : <>⚠️ No phone number on file for this voter.</>}
          </div>
        )}
      </div>
    </div>
  );
}

const wrapStyle = { display: 'flex', gap: '28px', flexWrap: 'wrap' };
const colStyle = { flex: '1 1 320px', minWidth: '280px' };
const headingStyle = { margin: '0 0 4px 0', fontSize: '18px' };
const subStyle = { margin: '0 0 14px 0', fontSize: '13px', opacity: 0.7 };

const registerInputStyle = {
  display: 'block', width: '100%', marginBottom: '10px', padding: '12px 14px',
  borderRadius: '10px', border: '1px solid var(--border-color)',
  backgroundColor: 'var(--bg-color)', color: 'var(--text-color)', boxSizing: 'border-box',
  fontSize: '14px', outline: 'none'
};

const tableWrapStyle = {
  maxHeight: '260px', overflowY: 'auto', borderRadius: '10px',
  border: '1px solid var(--border-color)'
};

const tableHeaderStyle = {
  position: 'sticky', top: 0, zIndex: 1,
  display: 'grid', gridTemplateColumns: '1.6fr 1.4fr', gap: '8px',
  padding: '10px 12px', backgroundColor: 'var(--card-bg)',
  borderBottom: '1px solid var(--border-color)',
  fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.6, fontWeight: 700
};

const tableBodyStyle = { padding: '0 12px' };

const rowStyle = {
  display: 'grid', gridTemplateColumns: '1.6fr 1.4fr', alignItems: 'center',
  gap: '8px', padding: '10px 0', borderBottom: '1px solid var(--border-color)', fontSize: '13px'
};

const mutedCenter = { textAlign: 'center', opacity: 0.6, padding: '20px 0', fontSize: '13px' };

const pagerStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px' };
const pagerBtnStyle = {
  background: 'none', border: '1px solid var(--border-color)', borderRadius: '20px',
  padding: '6px 14px', cursor: 'pointer', color: 'var(--text-color)', fontSize: '13px'
};

const checkBtnStyle = (loading) => ({
  width: '100%', padding: '13px', borderRadius: '30px', border: 'none',
  backgroundColor: 'var(--brand-primary, #003366)', color: 'white', fontWeight: 'bold',
  cursor: loading ? 'wait' : 'pointer', opacity: loading ? 0.7 : 1, fontSize: '14px'
});

const errorTextStyle = { color: 'var(--danger, #e74c3c)', fontSize: '13px', marginTop: '10px', textAlign: 'center' };

const resultBoxStyle = (ok) => ({
  marginTop: '12px', padding: '12px', borderRadius: '10px', fontSize: '14px', textAlign: 'center',
  backgroundColor: ok ? 'rgba(46,204,113,0.1)' : 'rgba(241,196,15,0.1)',
  border: `1px solid ${ok ? 'rgba(46,204,113,0.3)' : 'rgba(241,196,15,0.3)'}`
});
