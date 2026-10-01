import { MAX_IMAGE_BYTES, ACCEPT_IMAGES } from './imageFile';

// Pure helpers for the apply form (WP-6e). Kept out of the component so every case can be tested as a table.

const detailText = (d) => (typeof d === 'string' ? d
  : Array.isArray(d) ? d.map(x => x?.msg).filter(Boolean).join(' ') : '');

/** Error from an apply request -> one message an applicant can act on. Server wording is kept where it already
 *  tells the person what to do (student not found, name mismatch, window closed). */
export function mapApplyError(err, { online = true } = {}) {
  if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return 'Cancelled. Nothing was submitted.';
  const res = err?.response;
  if (!res) {
    if (!online) return "You're offline. Check your connection, then press Submit again. What you typed is kept.";
    if (err?.code === 'ECONNABORTED') return 'The server took too long to answer. Check your signal, then press Submit again.';
    return "Couldn't reach the server. Check your connection, then press Submit again.";
  }
  const text = detailText(res.data?.detail);
  switch (res.status) {
    case 400:
      if (/5\s?mb/i.test(text)) return 'That image is over 5 MB. Use a smaller photo or screenshot.';
      if (/already/i.test(text)) return text || 'An application for this student has already been submitted.';
      if (/only jpeg|allowed/i.test(text)) return 'That file type is not supported. Use a JPEG, PNG, WEBP or GIF image.';
      return text || 'Please check your entries and try again.';
    case 403: return text || 'Applications are not open right now.';
    case 404: return text || 'Your Student ID was not found on the voter register. Please contact IT support.';
    case 422: return text || 'Please check your entries and try again.';
    case 429: return 'Too many attempts. Wait a minute, then try again.';
    case 502: case 503: case 504: return 'The upload service is busy. Please try again in a moment.';
    default:
      if (res.status >= 500) return 'Something went wrong on our side. Please try again.';
      return text || 'Submission failed. Please try again.';
  }
}

export const FIELD_LABELS = {
  student_id: 'Student registration number',
  full_name: 'Full name',
  position_id: 'Position',
  manifesto: 'Manifesto',
  payment_method: 'Payment method',
  payment_proof: 'Payment receipt',
};
const ORDER = ['student_id', 'full_name', 'position_id', 'manifesto', 'payment_method', 'payment_proof'];

/** One pass over the whole form. Returns the missing fields in page order: [{ field, label }]. */
export function missingFields(v) {
  const empty = {
    student_id: !String(v.student_id || '').trim(),
    full_name: !String(v.full_name || '').trim(),
    position_id: !v.position_id,
    manifesto: !String(v.manifesto || '').trim(),
    payment_method: !v.payment_method,
    payment_proof: !v.payment_proof,
  };
  return ORDER.filter(f => empty[f]).map(field => ({ field, label: FIELD_LABELS[field] }));
}

export const missingMessage = (list) => `Please complete: ${list.map(x => x.label).join(', ')}.`;

/** Fixed analytics labels for a blocked submit. Never values, never file names. */
export function imageBlockReason(file) {
  if (!file) return 'missing_field';
  const types = ACCEPT_IMAGES.split(',');
  const okType = file.type ? types.includes(file.type) : /\.(jpe?g|png|webp|gif)$/i.test(file.name || '');
  if (!okType) return 'bad_file_type';
  return file.size > MAX_IMAGE_BYTES ? 'too_large' : 'bad_file_type';
}

/** Button/status text for the current step. The photo step is skipped when no photo was chosen. */
export function stepLabel(step, hasPhoto) {
  const names = hasPhoto
    ? ['Checking your details', 'Uploading photo', 'Uploading receipt', 'Submitting']
    : ['Checking your details', 'Uploading receipt', 'Submitting'];
  const i = Math.min(Math.max(step, 1), names.length);
  return `${names[i - 1]} (${i}/${names.length})`;
}

/** Same file picked again after a failed attempt -> same key, so it is not uploaded twice. */
export const fileKey = (f) => `${f.name}|${f.size}|${f.lastModified}`;
