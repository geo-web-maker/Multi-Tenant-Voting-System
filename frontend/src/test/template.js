/* global process */
import { setTemplateImpl } from '../template';

export const envIsBlueprint = process.env.VITE_UI_TEMPLATE === 'blueprint';
let mod;
const load = async () => (mod ??= await import('../templates/blueprint/index.js'));

// Named like hooks for readability in tests; they are plain functions, not React hooks.
/* eslint-disable react-hooks/rules-of-hooks */
export async function useBlueprint() {
  setTemplateImpl(await load());
}
export function useDefault() {
  setTemplateImpl(null);
}
export async function restoreTemplate() {
  return envIsBlueprint ? useBlueprint() : useDefault();
}
/* eslint-enable react-hooks/rules-of-hooks */
