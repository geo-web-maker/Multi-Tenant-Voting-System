import api from './api';
import { ADMIN_TOKEN_KEY } from './api';

// Guide 5.2: the commission login gets a fresh token for the panel view (and back).
// The old token is revoked server-side, so the new one replaces it in this tab.
export const PANEL_LINKED_KEY = 'panel_linked';

export async function switchHat() {
  const res = await api.post('/admin/switch-hat');
  sessionStorage.setItem(ADMIN_TOKEN_KEY, res.data.access_token);
  sessionStorage.setItem('admin_role', res.data.role);
  if (res.data.role === 'vetting') sessionStorage.setItem(PANEL_LINKED_KEY, '1');
  else sessionStorage.removeItem(PANEL_LINKED_KEY);
  window.location.reload();   // the view is chosen from the token's role on load
}
