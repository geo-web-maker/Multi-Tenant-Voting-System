import api from './api';

export const EXPORT_MODES = ['none', 'redacted', 'full'];
export const MODE_LABEL = { none: 'Off', redacted: 'Redacted', full: 'Full' };
export const MODE_HELP = {
  none: 'This IT admin has no export option.',
  redacted: 'Can export, with phone numbers masked (same as their on-screen list).',
  full: 'Can export the complete register with full phone numbers. No information is hidden.',
};

export const fetchExportPermission = () =>
  api.get('/admin/voters/export/permission').then((r) => r.data);

export const setItAdminExportMode = (studentId, mode) =>
  api.put(`/superadmin/it-admins/${encodeURIComponent(studentId)}/export-mode`, { mode }).then((r) => r.data);

// Content-Disposition: attachment; filename="x.csv"  ->  x.csv   (fallback when the header is hidden/absent)
export function filenameFromDisposition(header, fallback) {
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header || '');
  const name = m ? decodeURIComponent(m[1]).replace(/[\\/]/g, '_').trim() : '';
  return name || fallback;
}

// With responseType:'blob' an error body arrives as a Blob, not JSON. Also handles the "View as" pre-flight
// rejection (plain object) and network failures (no response).
export async function exportErrorMessage(e, fallback = 'Export failed. Please try again.') {
  if (!e?.response) return 'No response from the server. Check your connection and try again.';
  let data = e.response.data;
  try {
    if (typeof Blob !== 'undefined' && data instanceof Blob) data = JSON.parse(await data.text());
  } catch { data = null; }
  const d = data?.detail;
  if (typeof d === 'string' && d.trim()) return d;
  return fallback;
}

export async function downloadRegister(format) {
  const res = await api.post('/admin/voters/export', { format }, { responseType: 'blob', timeout: 120000 });
  const fallback = `voter-register.${format}`;
  const name = filenameFromDisposition(res.headers?.['content-disposition'], fallback);
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.style.display = 'none';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return { name, rows: Number(res.headers?.['x-export-rows'] ?? NaN), mode: res.headers?.['x-export-mode'] || '' };
}
