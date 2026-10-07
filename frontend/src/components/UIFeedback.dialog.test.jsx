import { useEffect } from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { UIFeedbackProvider, useConfirm, usePrompt } from './UIFeedback';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

// Runs under both templates: the dialog is the same component, blueprint only restyles it through classes.
const api = {};
const ask = (...a) => api.confirm(...a);
const askPrompt = (...a) => api.prompt(...a);
function Probe() {
  const confirm = useConfirm();
  const prompt = usePrompt();
  useEffect(() => { api.confirm = confirm; api.prompt = prompt; });
  return <button>trigger</button>;
}
const mount = () => render(<UIFeedbackProvider><Probe /></UIFeedbackProvider>);

afterEach(async () => { await restoreTemplate(); });

describe.each([['default', useDefault], ['blueprint', useBlueprint]])('in-app dialog (%s template)', (_name, use) => {
  it('is a labelled modal dialog with a title, message and two actions', async () => {
    await use();
    mount();
    let result; act(() => { result = ask('Remove this student?', { confirmText: 'Remove' }); });
    const dlg = await screen.findByRole('dialog', { name: 'Please confirm' });
    expect(dlg).toHaveAttribute('aria-modal', 'true');
    expect(dlg).toHaveAccessibleDescription('Remove this student?');
    expect(dlg.className).toContain('ui-dialog');
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await expect(result).resolves.toBe(true);
  });

  it('shows a visible title heading only in the blueprint template (default look unchanged)', async () => {
    await use();
    mount();
    act(() => { ask('Sure?'); });
    await screen.findByRole('dialog');
    const heading = screen.queryByRole('heading', { name: 'Please confirm' });
    if (_name === 'blueprint') expect(heading).not.toBeNull(); else expect(heading).toBeNull();
  });

  it('destructive confirm is an alertdialog that starts focus on Cancel; Escape cancels and focus returns', async () => {
    await use();
    mount();
    const trigger = screen.getByRole('button', { name: 'trigger' });
    trigger.focus();
    let result; act(() => { result = ask('Delete it?', { danger: true, title: 'Delete?' }); });
    await screen.findByRole('alertdialog', { name: 'Delete?' });
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    await expect(result).resolves.toBe(false);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(trigger).toHaveFocus();
  });

  it('Tab wraps inside the dialog', async () => {
    await use();
    mount();
    act(() => { ask('Sure?'); });
    await screen.findByRole('dialog');
    const ok = screen.getByRole('button', { name: 'OK' });
    ok.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(ok).toHaveFocus();
  });

  it('prompt returns the typed text, or null on Cancel', async () => {
    await use();
    mount();
    let result; act(() => { result = askPrompt('Why?', { placeholder: 'Reason' }); });
    fireEvent.change(await screen.findByPlaceholderText('Reason'), { target: { value: 'duplicate' } });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    await expect(result).resolves.toBe('duplicate');
    act(() => { result = askPrompt('Why?'); });
    await screen.findByRole('dialog', { name: 'Your input' });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await expect(result).resolves.toBeNull();
  });
});

describe('no native browser dialogs anywhere in the app', () => {
  it('window.confirm / alert / prompt are only referenced by the provider-less fallback', () => {
    const files = import.meta.glob('/src/**/*.{js,jsx}', { query: '?raw', import: 'default', eager: true });
    const hits = [];
    for (const [path, src] of Object.entries(files)) {
      if (/\.test\.|\/test\//.test(path)) continue;
      const code = src.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
      if (/window\.(confirm|alert|prompt)\s*\(/.test(code)) hits.push(path);
    }
    expect(hits).toEqual(['/src/components/UIFeedback.jsx']);
  });
});
