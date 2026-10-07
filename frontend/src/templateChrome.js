// Header <-> dashboard handshake for the Blueprint template (tiny, always bundled).
import { useSyncExternalStore } from 'react';

const EMPTY = { role: '', group: '', tab: '', tabIndex: 0, tabCount: 0, onLogout: null };
let state = EMPTY;
const subs = new Set();

export function setChrome(patch) {
  if (Object.keys(patch).every((k) => Object.is(state[k], patch[k]))) return; // no churn
  state = { ...state, ...patch };
  subs.forEach((f) => f());
}
export const resetChrome = () => setChrome(EMPTY);
export const useChrome = () =>
  useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => state,
  );
