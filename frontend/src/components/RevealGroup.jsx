/* eslint-disable react-refresh/only-export-components */
// (Exports a hook next to the component on purpose; splitting the file would touch every importer.)
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { LoadingBlock } from './Spinner.jsx';

/**
 * Show a set of independently-loading panels together instead of popping in one by one.
 *
 * Children stay mounted (so all their requests run in parallel) but are hidden behind a single
 * spinner until every child that called `useRevealReady()` reports ready. After the first reveal the
 * group never hides again, so background polling refreshes stay invisible. `timeoutMs` is a safety
 * net so one slow request can never keep the page blank.
 *
 * Outside a RevealGroup, `useRevealReady` does nothing, so panels keep working standalone.
 */
const RevealCtx = createContext(null);

export function useRevealReady(ready) {
  const ctx = useContext(RevealCtx);
  const idRef = useRef(null);
  if (idRef.current === null) idRef.current = Symbol('reveal');
  useEffect(() => {
    if (!ctx) return undefined;
    const id = idRef.current;
    ctx.report(id, Boolean(ready));
    return () => ctx.forget(id);
  }, [ctx, ready]);
}

export default function RevealGroup({ children, text = 'Loading…', timeoutMs = 8000 }) {
  const regs = useRef(new Map());
  const [version, setVersion] = useState(0);
  const [revealed, setRevealed] = useState(false);

  const report = useCallback((id, ready) => { regs.current.set(id, ready); setVersion(v => v + 1); }, []);
  const forget = useCallback(id => { regs.current.delete(id); }, []);
  const ctx = useMemo(() => ({ report, forget }), [report, forget]);

  // Checked in an effect (not inside report) so every child has registered before we decide.
  useEffect(() => {
    if (revealed || regs.current.size === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: `regs` is a ref (not reactive), so this effect is where we read it
    if ([...regs.current.values()].every(Boolean)) setRevealed(true);
  }, [version, revealed]);

  useEffect(() => {
    const t = setTimeout(() => setRevealed(true), timeoutMs);
    return () => clearTimeout(t);
  }, [timeoutMs]);

  return (
    <RevealCtx.Provider value={ctx}>
      {!revealed && <LoadingBlock text={text} />}
      <div style={revealed ? undefined : { display: 'none' }}>{children}</div>
    </RevealCtx.Provider>
  );
}
