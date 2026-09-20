// Shared logic for the two student-edit screens (superadmin "Student Changes" and the
// standalone IT admin screen). Only logic lives here: no layout, so the two UIs stay separate.
// Both screens call the SAME backend endpoint (POST /admin/students/edit).
import api from './api';

export const lookupStudents = (q) =>
  api.get('/admin/students/lookup', { params: { q } }).then((r) => r.data);

export const fetchEditHistory = (q = '') =>
  api.get('/admin/students/edit-history', { params: { q, limit: 100 } }).then((r) => r.data.entries);

export const saveStudentEdit = (body) =>
  api.post('/admin/students/edit', body).then((r) => r.data);

// Same rules as the backend's normalize_phone_number, so the preview matches what is saved.
export function previewPhone(raw) {
  let clean = String(raw || '').replace(/\D/g, '');
  if (clean.startsWith('0')) clean = '256' + clean.slice(1);
  else if (clean.length === 9 && (clean.startsWith('7') || clean.startsWith('4'))) clean = '256' + clean;
  return clean.length >= 10 && clean.length <= 15 ? clean : null;
}

const normId = (s) => String(s || '').trim().replace(/"/g, '').replace(/\s+/g, '').toLowerCase();
const cleanName = (s) => String(s || '').split(/\s+/).filter(Boolean).join(' ');

export function draftFromStudent(s) {
  return {
    original: s,
    full_name: s.full_name,
    new_student_id: s.student_id,
    phones: s.phone_numbers.map((n, i) => ({ key: `o${i}`, index: i, original: n, value: n, removed: false })),
  };
}

let newKey = 0;
export const withNewPhoneRow = (d) => ({
  ...d, phones: [...d.phones, { key: `n${newKey++}`, index: null, original: null, value: '', removed: false }],
});

/** Everything a screen needs to render "current -> new" and to send the save. */
export function computeChanges(d) {
  const rows = [];
  const errors = [];
  const ops = { change: [], remove: [], add: [] };

  const name = cleanName(d.full_name);
  if (!name) errors.push('Name cannot be empty.');
  else if (name !== d.original.full_name) rows.push({ id: 'name', label: 'Name', from: d.original.full_name, to: name });

  const sid = normId(d.new_student_id);
  if (!sid) errors.push('Registration number cannot be empty.');
  else if (sid !== d.original.student_id) {
    rows.push({ id: 'sid', label: 'Registration number', from: d.original.student_id, to: sid });
  }

  d.phones.forEach((p) => {
    if (p.index !== null) {
      if (p.removed) {
        rows.push({ id: p.key, label: 'Phone removed', from: p.original, to: null });
        ops.remove.push({ op: 'remove', index: p.index, expected_old: p.original });
        return;
      }
      const n = previewPhone(p.value);
      if (!n) errors.push(`"${p.value}" is not a valid phone number.`);
      else if (n !== p.original) {
        rows.push({ id: p.key, label: 'Phone changed', from: p.original, to: n });
        ops.change.push({ op: 'change', index: p.index, expected_old: p.original, number: p.value });
      }
    } else if (!p.removed && p.value.trim()) {
      const n = previewPhone(p.value);
      if (!n) errors.push(`"${p.value}" is not a valid phone number.`);
      else rows.push({ id: p.key, label: 'Phone added', from: null, to: n });
      if (n) ops.add.push({ op: 'add', number: p.value });
    }
  });

  const remaining = d.phones.filter((p) => !p.removed && (p.index !== null || p.value.trim())).length;
  const warnings = [];
  if (rows.length && remaining === 0) {
    warnings.push('This student will have no phone number and cannot receive a voting OTP.');
  }
  return { rows, errors, warnings, ops, hasChanges: rows.length > 0 };
}

/** Removes go highest-index first so earlier positions stay valid on the server. */
export function buildPayload(d, reason) {
  const { rows, ops } = computeChanges(d);
  const has = (id) => rows.some((r) => r.id === id);
  return {
    student_id: d.original.student_id,
    full_name: has('name') ? cleanName(d.full_name) : undefined,
    new_student_id: has('sid') ? d.new_student_id : undefined,
    phone_ops: [...ops.change, ...[...ops.remove].sort((a, b) => b.index - a.index), ...ops.add],
    reason: reason.trim(),
  };
}

export const EVENT_LABELS = {
  student_name_changed: 'Name changed',
  student_registration_number_changed: 'Registration number changed',
  phone_added: 'Phone added',
  phone_removed: 'Phone removed',
  phone_changed: 'Phone changed',
};

// FastAPI returns `detail` as a string, or as an array on validation errors (422).
export function errMsg(e, fallback) {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string' && d.trim()) return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  return fallback;
}
