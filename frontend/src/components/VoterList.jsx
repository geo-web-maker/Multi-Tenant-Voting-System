import React, { useEffect, useState } from 'react';
import api from '../api';
import { regNo } from '../regNo';
import { Icon } from './icons.jsx';
import { errMsg } from '../studentEdit';
import { getTemplate } from '../template';

export default function VoterList({ showStatus = false, onEdit, onRemove, onResetOtp }) {
  const [fields, setFields] = useState([]);
  const [q, setQ] = useState('');
  const [missingPhone, setMissingPhone] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [data, setData] = useState({ results: [], total: 0, page: 1, page_size: 25 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadFields = async () => {
    try { setFields((await api.get('/admin/voter-fields')).data); }
    catch (e) { setError(errMsg(e, 'Could not load voter fields.')); }
  };
  const load = async () => {
    setLoading(true); setError('');
    try {
      const r = await api.get('/admin/voters/list', { params: { q, page, page_size: pageSize, missing_phone: missingPhone } });
      setData(r.data);
    } catch (e) { setError(errMsg(e, 'Could not load voters.')); }
    finally { setLoading(false); }
  };
  useEffect(() => { loadFields(); }, []);
  useEffect(() => { load(); }, [q, page, missingPhone]); // eslint-disable-line react-hooks/exhaustive-deps

  const pages = Math.max(1, Math.ceil(data.total / pageSize));
  const start = data.total ? ((data.page - 1) * pageSize) + 1 : 0;
  const end = Math.min(data.page * pageSize, data.total);
  const bp = getTemplate();
  const L = (l) => (bp ? { 'data-l': l } : undefined);   // mobile card-row labels, Blueprint only

  return <div style={box}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
      <div style={{ flex: '1 1 280px' }}>
        <input style={inp} value={q} maxLength={80} onChange={e => { setQ(e.target.value); setPage(1); }}
          placeholder="Search by name or registration number" aria-label="Search voters" />
      </div>
      <label style={check}><input type="checkbox" checked={missingPhone} onChange={e => { setMissingPhone(e.target.checked); setPage(1); }} /> No phone on file</label>
      <button type="button" style={ghost} onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
    </div>
    {error && <p style={errorStyle}><Icon name="warning" /> {error}</p>}
    <div className="table-scroll-y voter-table" style={{ overflowX: 'auto', border: '1px solid var(--border-color)', borderRadius: 10 }}>
      <table style={table} className={bp ? 'bp-rs' : undefined}>
        <thead><tr>
          <th style={th}>Name</th><th style={th}>Registration Number</th><th style={th}>Phone on file</th>
          {fields.map(f => <th key={f.key} style={th}>{f.label}</th>)}
          {showStatus && <th style={th}>Status</th>}
          <th style={th}>Actions</th>
        </tr></thead>
        <tbody>
          {data.results.map(v => <tr key={v.student_id}>
            <td style={td} {...L('Name')}>{v.full_name}</td><td style={td} {...L('Registration Number')}><code>{regNo(v.student_id)}</code></td>
            <td style={td} {...L('Phone on file')}>{v.phone_numbers?.length ? v.phone_numbers.join(', ') : <span style={{ opacity: .55 }}>None</span>}</td>
            {fields.map(f => <td key={f.key} style={td} {...L(f.label)}>{v.attrs?.[f.key] || <span style={{ opacity: .45 }}>—</span>}</td>)}
            {showStatus && <td style={td} {...L('Status')}>{bp
              ? <bp.StatusPill tone={v.has_voted ? 'ok' : 'warn'}>{v.has_voted ? 'VOTED' : (v.last_status || 'IDLE').toUpperCase()}</bp.StatusPill>
              : <span style={status(v.has_voted)}>{v.has_voted ? 'VOTED' : (v.last_status || 'IDLE').toUpperCase()}</span>}</td>}
            <td style={td} {...L('Actions')}><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button style={smallBtn} onClick={() => onEdit?.(v.student_id)}>Edit</button>
              {onRemove && <button style={smallBtn} onClick={() => onRemove(v)}>Remove</button>}
              {onResetOtp && <button style={smallBtn} onClick={() => onResetOtp(v.student_id)}>Reset OTP</button>}
            </div></td>
          </tr>)}
          {!loading && data.results.length === 0 && <tr><td style={empty} colSpan={fields.length + (showStatus ? 5 : 4)}>No voters found.</td></tr>}
        </tbody>
      </table>
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
      <span style={{ fontSize: 12, opacity: .65 }}>{start}–{end} of {data.total}</span>
      <div style={{ display: 'flex', gap: 6 }}>
        <button style={ghost} disabled={page <= 1 || loading} onClick={() => setPage(p => p - 1)}>Previous</button>
        <span style={{ padding: '9px 8px', fontSize: 12 }}>Page {page} of {pages}</span>
        <button style={ghost} disabled={page >= pages || loading} onClick={() => setPage(p => p + 1)}>Next</button>
      </div>
    </div>
  </div>;
}

const box = { padding: 16, border: '1px solid var(--border-color)', borderRadius: 12, background: 'var(--bg-color)' };
const inp = { padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, width: '100%', boxSizing: 'border-box', minHeight: 44 };
const ghost = { padding: '9px 12px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: 8, cursor: 'pointer', fontSize: 12, minHeight: 40 };
const smallBtn = { ...ghost, padding: '6px 9px', minHeight: 34 };
const check = { display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, whiteSpace: 'nowrap' };
const table = { width: '100%', borderCollapse: 'collapse', minWidth: 760 };
const th = { textAlign: 'left', padding: '9px 10px', borderBottom: '1px solid var(--border-color)', fontSize: 11, opacity: .65, whiteSpace: 'nowrap' };
const td = { padding: '9px 10px', borderBottom: '1px solid var(--border-color)', fontSize: 12, verticalAlign: 'top' };
const empty = { padding: 30, textAlign: 'center', opacity: .55, fontSize: 13 };
const errorStyle = { color: 'var(--danger)', fontSize: 12, fontWeight: 600 };
const status = voted => ({ fontSize: 10, fontWeight: 700, padding: '3px 7px', borderRadius: 8, color: voted ? 'var(--success)' : 'var(--warning)', background: voted ? 'color-mix(in srgb, var(--success) 15%, transparent)' : 'color-mix(in srgb, var(--warning) 15%, transparent)' });
