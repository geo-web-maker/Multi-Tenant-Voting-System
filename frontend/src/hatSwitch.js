import { safeSessionStorage } from './storage.js';
import api from './api';
import { ADMIN_TOKEN_KEY } from './api';

// Guide 5.2: any admin login (commissioner, IT admin, overseer, financial controller) gets a fresh token for
// the panel view (and back to their own role).
// The old token is revoked server-side, so the new one replaces it in this tab.
export const PANEL_LINKED_KEY = 'panel_linked';
export const HAT_BACK_LABEL_KEY = 'panel_back_label';   // e.g. "IT Admin": what the panel's switch-back button says

export async function switchHat() {
  const res = await api.post('/admin/switch-hat');
  safeSessionStorage.setItem(ADMIN_TOKEN_KEY, res.data.access_token);
  safeSessionStorage.setItem('admin_role', res.data.role);
  if (res.data.role === 'vetting') {
    safeSessionStorage.setItem(PANEL_LINKED_KEY, '1');
    if (res.data.back_label) safeSessionStorage.setItem(HAT_BACK_LABEL_KEY, res.data.back_label);
  } else {
    safeSessionStorage.removeItem(PANEL_LINKED_KEY);
    safeSessionStorage.removeItem(HAT_BACK_LABEL_KEY);
  }
  window.location.reload();   // the view is chosen from the token's role on load
}
