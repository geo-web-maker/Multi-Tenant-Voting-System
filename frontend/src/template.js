// UI template registry. The default UI is `null`; the Blueprint Console is registered once, before first render
// (see main.jsx). Seams call getTemplate() at RENDER time, never at import time.
export const UI_TEMPLATES = ['default', 'blueprint'];
export const resolveTemplate = (raw) => (raw === 'blueprint' ? 'blueprint' : 'default');
export const UI_TEMPLATE = resolveTemplate(import.meta.env.VITE_UI_TEMPLATE);

let impl = null; // null => the standard UI
export function setTemplateImpl(mod) {
  impl = mod || null;
  if (typeof document !== 'undefined') {
    if (impl) document.documentElement.dataset.template = 'blueprint';
    else delete document.documentElement.dataset.template;
  }
}
export const getTemplate = () => impl;
