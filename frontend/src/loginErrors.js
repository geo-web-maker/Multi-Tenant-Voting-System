// Turn the server's identity-check error into guidance with a next step (guide 4.3). The server's wording is
// already clear but ends there; the voter needs to know what to DO. Matching is on the stable `detail`
// text and `reason` code the backend sends, and anything unrecognised falls through to the server's own text.

import { getIdText } from './idText';

/**
 * @param {string|object} detail  err.response.data.detail
 * @param {string} [reason]       err.response.data.reason (when present)
 * @returns {{ title: string, message: string, action?: 'check_register'|'contact_change', support?: boolean }}
 */
export function loginGuidance(detail, reason, text = getIdText()) {
  const d = typeof detail === 'string' ? detail : '';
  const has = (re) => re.test(d);

  if (reason === 'not_on_roll' || has(/student id not found/i)) {
    return { title: `${text.nounCap} not found`,
      message: `We could not find that ${text.noun}. ${text.hint ? text.hint + ' Then check' : 'Check'} the voter register to confirm you are on it.`,
      action: 'check_register', support: true };
  }
  if (reason === 'name_mismatch' || has(/name mismatch/i)) {
    return { title: 'Names do not match the register',
      message: 'Enter your names exactly as they appear on the voter register (surname first is fine). Check the register if you are unsure how your names are written.',
      action: 'check_register' };
  }
  if (reason === 'already_voted' || has(/already voted/i)) {
    return { title: 'Already voted',
      message: `Our records show this ${text.noun} has already voted. If you did not vote, contact support.`, support: true };
  }
  if (reason === 'no_phone' || has(/no phone found/i)) {
    return { title: 'No phone number on file',
      message: 'There is no phone number on file for you, so we cannot send a code. Request a contact change so one can be added.',
      action: 'contact_change' };
  }
  if (reason === 'sms_failed' || has(/sms delivery failed/i)) {
    return { title: 'We could not send the code',
      message: 'We could not send the code. Wait a minute and try again, or contact support.', support: true };
  }
  if (typeof detail === 'object' && detail) return { title: 'Login Error', message: JSON.stringify(detail) };
  return { title: 'Login Error', message: d || 'Verification Failed' };
}

/** Pure cleanup for a pasted/typed code: digits only, max 6 ("123 456" -> "123456"). */
export const cleanOtp = (raw) => String(raw || '').replace(/\D/g, '').slice(0, 6);

/** Extra line for the "code sent" message when the SMS gateway did not confirm delivery. */
export const UNCONFIRMED_DELIVERY_NOTE =
  ' If no SMS arrives within 2 minutes, tap Resend — you will get the same code.';
