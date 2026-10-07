// Floating ballot action bar (BP-T4). Presentation only: BallotBox owns the ballot and passes the handlers in.
// Publishes its height to --bottom-bar-height (the Help FAB reads it) and clears it on unmount.
import { useEffect, useRef } from 'react';

export default function BottomDock({ count, onClear, onReview }) {
  const ref = useRef(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const root = document.documentElement;
    const publish = () => root.style.setProperty('--bottom-bar-height', `${node.getBoundingClientRect().height}px`);
    publish();
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(publish);
    ro?.observe(node);
    return () => { ro?.disconnect(); root.style.removeProperty('--bottom-bar-height'); };
  }, []);
  const empty = count === 0;
  return (
    <div ref={ref} className="bp-dock">
      <button type="button" className="bp-btn bp-ghost" onClick={onClear} disabled={empty}>Clear All</button>
      <button type="button" className="bp-btn" onClick={onReview} disabled={empty}>REVIEW & SUBMIT ({count})</button>
    </div>
  );
}
