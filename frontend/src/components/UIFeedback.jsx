/* eslint-disable react-refresh/only-export-components */
// (This file intentionally exports both the provider component and its
// hooks together — splitting them would only help Vite's dev-mode Fast
// Refresh, not the production build, and keeping the toast/confirm/prompt
// API next to the component that implements it is worth that tradeoff.)
import React, { createContext, useCallback, useContext, useRef, useState } from 'react';

// Replaces window.alert() / window.confirm() / window.prompt() app-wide with
// an in-app toast + confirm-dialog system. The native dialogs this replaces:
//   - block the entire tab and can't be styled or show a loading state
//   - aren't screen-reader friendly
//   - for destructive actions, are easy to click through on muscle memory
//     (a single native confirm() is thin protection for something like a
//     full election reset)
// This keeps the same call-site ergonomics (toast(msg) instead of alert(msg),
// await confirm(msg) instead of window.confirm(msg)) so existing handlers
// only need their alert/confirm/prompt calls swapped, not restructured —
// but confirm() now returns a real Promise<boolean> so callers that used to
// do `if (window.confirm(...))` need `if (await confirm(...))` instead.

const UIFeedbackContext = createContext(null);

export function useToast() {
  const ctx = useContext(UIFeedbackContext);
  if (!ctx) throw new Error('useToast must be used within <UIFeedbackProvider>');
  return ctx.toast;
}

export function usePrompt() {
  const ctx = useContext(UIFeedbackContext);
  if (!ctx) throw new Error('usePrompt must be used within <UIFeedbackProvider>');
  return ctx.prompt;
}

export function useConfirm() {
  const ctx = useContext(UIFeedbackContext);
  if (!ctx) throw new Error('useConfirm must be used within <UIFeedbackProvider>');
  return ctx.confirm;
}

let toastIdCounter = 0;

const TOAST_EXIT_MS = 180; // must match .toast-out duration in index.css

export function UIFeedbackProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const [dialog, setDialog] = useState(null); // { mode: 'confirm'|'prompt', message, danger, confirmText, cancelText, requireText, inputValue }
  const resolverRef = useRef(null);

  const toast = useCallback((message, opts = {}) => {
    const id = ++toastIdCounter;
    const kind = opts.kind || 'info'; // 'info' | 'success' | 'error'
    setToasts(prev => [...prev, { id, message, kind, exiting: false }]);
    const duration = opts.duration ?? 5000;
    if (duration > 0) {
      setTimeout(() => dismissToast(id), duration);
    }
  }, []);

  // Marks the toast as exiting (triggers the slide/fade-out), then removes
  // it from state once that animation has had time to finish.
  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.map(t => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, TOAST_EXIT_MS);
  }, []);

  // confirm(message, { danger, confirmText, cancelText, requireText }) -> Promise<boolean>
  // requireText: if set, the confirm button stays disabled until the admin
  // types this exact phrase — the in-app equivalent of the old
  // window.prompt("Type 'RESET' to confirm") pattern, but as a real modal
  // field instead of a second native dialog stacked on the first.
  const confirm = useCallback((message, opts = {}) => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setDialog({
        mode: 'confirm',
        message,
        danger: !!opts.danger,
        confirmText: opts.confirmText || (opts.danger ? 'Confirm' : 'OK'),
        cancelText: opts.cancelText || 'Cancel',
        requireText: opts.requireText || null,
        inputValue: '',
      });
    });
  }, []);

  // prompt(message, { placeholder, defaultValue }) -> Promise<string|null>
  // Free-text input, resolves with the typed value (possibly empty string)
  // on confirm, or null on cancel — same contract as window.prompt(), used
  // for optional free-text like "why are you withdrawing this request?"
  // rather than a typed-phrase safety gate (that's confirm's requireText).
  const prompt = useCallback((message, opts = {}) => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setDialog({
        mode: 'prompt',
        message,
        danger: false,
        confirmText: opts.confirmText || 'OK',
        cancelText: opts.cancelText || 'Cancel',
        placeholder: opts.placeholder || '',
        inputValue: opts.defaultValue || '',
      });
    });
  }, []);

  const resolveDialog = (result) => {
    if (resolverRef.current) {
      resolverRef.current(result);
      resolverRef.current = null;
    }
    setDialog(null);
  };

  const canConfirm = dialog?.mode === 'prompt'
    ? true
    : (!dialog?.requireText || dialog.inputValue === dialog.requireText);

  return (
    <UIFeedbackContext.Provider value={{ toast, confirm, prompt }}>
      {children}

      {/* Toasts */}
      <div style={toastContainerStyle}>
        {toasts.map(t => (
          <div key={t.id} style={{ ...toastStyle, ...toastKindStyle[t.kind] }}
            className={t.exiting ? 'toast-out' : 'toast-in'} onClick={() => dismissToast(t.id)}>
            {t.message}
          </div>
        ))}
      </div>

      {/* Confirm / prompt dialog */}
      {dialog && (
        <div style={overlayStyle} className="overlay-fade-in" onClick={() => resolveDialog(dialog.mode === 'prompt' ? null : false)}>
          <div style={dialogStyle} className="panel-fade-in" onClick={(e) => e.stopPropagation()}>
            <div style={{ whiteSpace: 'pre-wrap', marginBottom: (dialog.requireText || dialog.mode === 'prompt') ? '16px' : '24px', color: 'var(--text-color)', fontSize: '15px', lineHeight: 1.5 }}>
              {dialog.message}
            </div>
            {dialog.mode === 'prompt' && (
              <div style={{ marginBottom: '20px' }}>
                <input
                  autoFocus
                  type="text"
                  value={dialog.inputValue}
                  placeholder={dialog.placeholder}
                  onChange={(e) => setDialog(d => ({ ...d, inputValue: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') resolveDialog(dialog.inputValue); }}
                  style={dialogInputStyle}
                />
              </div>
            )}
            {dialog.mode === 'confirm' && dialog.requireText && (
              <div style={{ marginBottom: '20px' }}>
                <div style={{ fontSize: '13px', color: 'var(--text-color)', opacity: 0.7, marginBottom: '6px' }}>
                  Type <strong>{dialog.requireText}</strong> to confirm:
                </div>
                <input
                  autoFocus
                  type="text"
                  value={dialog.inputValue}
                  onChange={(e) => setDialog(d => ({ ...d, inputValue: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter' && canConfirm) resolveDialog(true); }}
                  style={dialogInputStyle}
                  placeholder={dialog.requireText}
                />
              </div>
            )}
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button style={cancelBtnStyle} onClick={() => resolveDialog(dialog.mode === 'prompt' ? null : false)}>{dialog.cancelText}</button>
              <button
                style={{ ...confirmBtnStyle, ...(dialog.danger ? dangerBtnStyle : {}), opacity: canConfirm ? 1 : 0.5, cursor: canConfirm ? 'pointer' : 'not-allowed' }}
                disabled={!canConfirm}
                onClick={() => canConfirm && resolveDialog(dialog.mode === 'prompt' ? dialog.inputValue : true)}
              >
                {dialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </UIFeedbackContext.Provider>
  );
}

const toastContainerStyle = {
  position: 'fixed', top: '16px', right: '16px', zIndex: 5000,
  display: 'flex', flexDirection: 'column', gap: '8px', maxWidth: '360px',
};

const toastStyle = {
  padding: '12px 16px', borderRadius: '10px', color: '#fff', fontSize: '14px',
  boxShadow: '0 8px 20px rgba(0,0,0,0.25)', cursor: 'pointer', lineHeight: 1.4,
};

const toastKindStyle = {
  info:    { backgroundColor: '#334155' },
  success: { backgroundColor: '#16a34a' },
  error:   { backgroundColor: '#dc2626' },
};

const overlayStyle = {
  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
  backgroundColor: 'rgba(15, 23, 42, 0.75)', display: 'flex',
  justifyContent: 'center', alignItems: 'center', zIndex: 5001, backdropFilter: 'blur(3px)',
  padding: '16px',
};

const dialogStyle = {
  backgroundColor: 'var(--card-bg)', padding: '24px', borderRadius: '16px',
  width: '100%', maxWidth: '420px', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)',
  border: '1px solid var(--border-color)',
};

const dialogInputStyle = {
  width: '100%', padding: '10px 12px', borderRadius: '6px',
  border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-color)',
  color: 'var(--text-color)', boxSizing: 'border-box', fontSize: '14px',
};

const cancelBtnStyle = {
  padding: '10px 18px', borderRadius: '8px', border: '1px solid var(--border-color)',
  backgroundColor: 'transparent', color: 'var(--text-color)', cursor: 'pointer', fontWeight: 500,
};

const confirmBtnStyle = {
  padding: '10px 18px', borderRadius: '8px', border: 'none',
  backgroundColor: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600,
};

const dangerBtnStyle = {
  backgroundColor: '#dc2626',
};

/**
 * Bounded, scrollable container for lists that can grow without limit (requests, admins, logs…),
 * so the menus below them stay reachable. Height is capped relative to the viewport.
 */
export function ScrollList({ children, maxHeight = '65vh', style }) {
  return (
    <div style={{ maxHeight, overflowY: 'auto', WebkitOverflowScrolling: 'touch', overscrollBehavior: 'contain', paddingRight: 4, ...style }}>
      {children}
    </div>
  );
}
