import { useEffect, useRef } from 'react';

/**
 * Measures the DOM node it's attached to and publishes its rendered height
 * as a CSS custom property on <html>, so other fixed-position elements
 * (like the Help FAB) can react to it without prop-drilling or hardcoded
 * offsets. Automatically re-measures on resize/content changes via
 * ResizeObserver, and cleans up the variable on unmount so it never leaks
 * a stale value onto a page that no longer has this bar.
 *
 * Usage:
 *   const barRef = useReportedHeight('--bottom-bar-height');
 *   <div ref={barRef} style={footerBarStyle}>...</div>
 */
export default function useReportedHeight(cssVarName) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const publish = () => {
      document.documentElement.style.setProperty(
        cssVarName,
        `${node.getBoundingClientRect().height}px`
      );
    };

    publish();

    const observer = new ResizeObserver(publish);
    observer.observe(node);

    return () => {
      observer.disconnect();
      document.documentElement.style.removeProperty(cssVarName);
    };
  }, [cssVarName]);

  return ref;
}
