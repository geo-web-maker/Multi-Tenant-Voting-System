import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './icons.jsx';
import { trackPage } from '../analytics';

const RAIL_COLLAPSED_KEY = 'tabbar-rail-collapsed';

// Shared tab-bar component used by every admin dashboard.
//
// Usage:
//   <TabBar tabs={flatTabs} activeTab={activeTab} onChange={setActiveTab} />
//   <TabBar groups={groupedTabs} activeTab={activeTab} onChange={setActiveTab} />
//
// `tabs`   — flat list of { id, label, count? }. Desktop wraps onto extra
//            rows, mobile scrolls horizontally with a real edge-fade on
//            whichever side still has more content.
// `groups` — [{ label, tabs: [...] }]. Desktop renders a single sticky
//            rail: one section header per group, a vertical list of its
//            tabs underneath — nothing to wrap, nothing to crop. Mobile
//            ignores the grouping and renders every tab as one flat,
//            horizontally-scrollable pill row — the same row (and the
//            same ScrollRow/PillButton scroll mechanism) flat dashboards
//            use, rather than a separate group-pill-row-plus-vertical-
//            list hybrid with its own, different-looking scroll behavior.
//
// Grouped + desktop returns a self-contained <nav> meant to sit beside
// the page's content, not above it — wrap both in a `.dash-body` flex
// row (`.dash-main` on the content column) so it lays out as a rail on
// desktop and stacks on mobile without any JS breakpoint duplication.

const MOBILE_QUERY = '(max-width: 768px)';

// Scrolls `el` into view within `container` ONLY — never via the browser's
// native scrollIntoView, which walks up the ancestor chain looking for
// *any* scrollable box (including html/body under overflow-x: hidden) and
// can end up shifting the whole document sideways with no way for the user
// to scroll it back. This computes the element's position relative to the
// one container we actually mean to scroll and nudges just that container,
// only as far as needed to bring the element fully into view — nothing
// outside `container` is ever touched.
function scrollNearest(container, el, axis) {
  if (!container || !el) return;
  const cRect = container.getBoundingClientRect();
  const eRect = el.getBoundingClientRect();
  if (axis === 'x') {
    const pos = container.scrollLeft;
    const elStart = eRect.left - cRect.left + pos;
    const elEnd = elStart + eRect.width;
    if (elStart < pos) container.scrollTo({ left: elStart, behavior: 'smooth' });
    else if (elEnd > pos + container.clientWidth) container.scrollTo({ left: elEnd - container.clientWidth, behavior: 'smooth' });
  } else {
    const pos = container.scrollTop;
    const elStart = eRect.top - cRect.top + pos;
    const elEnd = elStart + eRect.height;
    if (elStart < pos) container.scrollTo({ top: elStart, behavior: 'smooth' });
    else if (elEnd > pos + container.clientHeight) container.scrollTo({ top: elEnd - container.clientHeight, behavior: 'smooth' });
  }
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches
  );
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const handler = e => setIsMobile(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);
  return isMobile;
}

// A horizontally-scrollable row: click-and-drag to scroll, and real
// edge-fades (via the .fade-left / .fade-right classes in index.css)
// that only show when there's actually more content that way. Shift +
// mouse-wheel scrolling needs no JS at all — browsers do that for free
// on any overflow-x: auto element.
function ScrollRow({ children, rowClassName = '', showArrows = false, innerRef, forceScroll = false }) {
  const localRef = useRef(null);
  const ref = innerRef || localRef;
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);
  const drag = useRef({ active: false, startX: 0, startScroll: 0, moved: false });

  const updateEdges = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setCanLeft(el.scrollLeft > 2);
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    updateEdges();
    if (!el) return undefined;
    el.addEventListener('scroll', updateEdges, { passive: true });
    const ro = new ResizeObserver(updateEdges);
    ro.observe(el);
    window.addEventListener('resize', updateEdges);
    return () => {
      el.removeEventListener('scroll', updateEdges);
      ro.disconnect();
      window.removeEventListener('resize', updateEdges);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateEdges, children]);

  const onMouseDown = e => {
    const el = ref.current;
    if (!el) return;
    drag.current = { active: true, startX: e.clientX, startScroll: el.scrollLeft, moved: false };
  };
  const onMouseMove = e => {
    if (!drag.current.active) return;
    const el = ref.current;
    const dx = e.clientX - drag.current.startX;
    if (Math.abs(dx) > 3) drag.current.moved = true;
    el.scrollLeft = drag.current.startScroll - dx;
  };
  const endDrag = () => { drag.current.active = false; };
  // A drag that moved shouldn't also register as a click on whatever tab
  // the cursor happens to land on.
  const onClickCapture = e => {
    if (drag.current.moved) {
      e.stopPropagation();
      e.preventDefault();
      drag.current.moved = false;
    }
  };

  let fadeClass = '';
  if (canLeft && canRight) fadeClass = 'fade-left fade-right';
  else if (canLeft) fadeClass = 'fade-left';
  else if (canRight) fadeClass = 'fade-right';

  return (
    <div style={scrollRowOuter} className="tabbar-scroll-outer">
      {showArrows && canLeft && (
        <button
          type="button"
          aria-label="Scroll left"
          onClick={() => ref.current?.scrollBy({ left: -Math.round(ref.current.clientWidth * 0.7), behavior: 'smooth' })}
          style={{ ...arrowBtn, left: '-2px' }}
        >‹</button>
      )}
      <div
        ref={ref}
        className={`tabbar-row ${rowClassName} ${fadeClass}`}
        style={forceScroll ? scrollRowInnerForced : scrollRowInner}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
        onClickCapture={onClickCapture}
      >
        {children}
      </div>
      {showArrows && canRight && (
        <button
          type="button"
          aria-label="Scroll right"
          onClick={() => ref.current?.scrollBy({ left: Math.round(ref.current.clientWidth * 0.7), behavior: 'smooth' })}
          style={{ ...arrowBtn, right: '-2px' }}
        >›</button>
      )}
    </div>
  );
}

function PillButton({ t, isActive, onChange, tabRef }) {
  return (
    <button
      key={t.id}
      ref={tabRef}
      onClick={() => onChange(t.id)}
      className={`tabbar-pill${isActive ? ' is-active' : ''}`} data-track={`tab-${t.id}`}
    >
      {t.label}
      {t.count !== undefined && t.count !== null && <span style={countPillStyle}>{t.count}</span>}
    </button>
  );
}

function ListItem({ t, isActive, onChange, tabRef }) {
  return (
    <button
      key={t.id}
      ref={tabRef}
      onClick={() => onChange(t.id)}
      className={`tabbar-list-item${isActive ? ' is-active' : ''}`} data-track={`tab-${t.id}`}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {t.label}
      </span>
      {t.count !== undefined && t.count !== null && <span style={countPillStyle}>{t.count}</span>}
    </button>
  );
}

export default function TabBar({ tabs, groups, activeTab, onChange, className = '' }) {
  const isMobile = useIsMobile();
  useEffect(() => {
    const role = sessionStorage.getItem('admin_role');
    if (role && activeTab) trackPage(`${role}:${String(activeTab).toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 40)}`);
  }, [activeTab]);
  const flatMode = !groups || groups.length === 0;
  const effectiveGroups = flatMode ? [{ label: null, tabs: tabs || [] }] : groups;

  const activeGroupIndex = Math.max(0, effectiveGroups.findIndex(g => g.tabs.some(t => t.id === activeTab)));

  // Desktop rail only, now — collapsed to a strip of per-group icons,
  // remembered across visits. Mobile has no group-level UI of its own
  // to collapse: it's one flat pill row, same as flatMode.
  const [railCollapsed, setRailCollapsed] = useState(() => {
    try { return window.localStorage.getItem(RAIL_COLLAPSED_KEY) === '1'; }
    catch { return false; }
  });
  useEffect(() => {
    try { window.localStorage.setItem(RAIL_COLLAPSED_KEY, railCollapsed ? '1' : '0'); }
    catch { /* storage unavailable — collapse state just won't persist */ }
  }, [railCollapsed]);

  const tabRefs = useRef({});
  const groupRefs = useRef({});
  // Only ever one of these two is mounted at a time, matching whichever
  // branch below is rendering — nothing is ever scrolled outside whichever
  // one is currently active.
  const flatRowRef = useRef(null);   // flat mode, OR grouped+mobile: horizontal pill row
  const railRef = useRef(null);      // grouped, desktop: vertical rail
  // When a collapsed-rail icon is clicked, the rail expands on this render
  // and the group header should scroll into view on the next one.
  const pendingGroupScroll = useRef(null);
  useEffect(() => {
    if (!railCollapsed && pendingGroupScroll.current != null) {
      scrollNearest(railRef.current, groupRefs.current[pendingGroupScroll.current], 'y');
      pendingGroupScroll.current = null;
    }
  }, [railCollapsed]);

  // Auto-scroll the active tab into view whenever it changes — including
  // on first load. isMobile takes the same flat-row path as flatMode now
  // (see the render branch below), so it scrolls the same ref the same way.
  useEffect(() => {
    const el = tabRefs.current[activeTab];
    if (flatMode || isMobile) scrollNearest(flatRowRef.current, el, 'x');
    else scrollNearest(railRef.current, el, 'y');
  }, [activeTab, isMobile, flatMode]);

  // ── Flat mode, OR grouped mode on mobile: one row, wraps on desktop,
  //    scrolls on mobile. Grouped dashboards used to get a separate
  //    group-pill row + toggle + vertical list on mobile — a hybrid with
  //    two scroll axes and no clear card boundary around either piece.
  //    Financial's plain flat row reads far cleaner on a phone, so mobile
  //    now always gets that same single scrollable row, whether or not
  //    the dashboard defines groups; only the desktop rail below still
  //    uses the grouped layout. --
  if (flatMode || isMobile) {
    const allTabs = flatMode ? effectiveGroups[0].tabs : effectiveGroups.flatMap(g => g.tabs);
    return (
      <ScrollRow innerRef={flatRowRef} rowClassName={`tab-scroll no-print ${className}`} showArrows={!isMobile} forceScroll={isMobile}>
        {allTabs.map(t => (
          <PillButton
            key={t.id}
            t={t}
            isActive={activeTab === t.id}
            onChange={onChange}
            tabRef={el => { tabRefs.current[t.id] = el; }}
          />
        ))}
      </ScrollRow>
    );
  }

  // ── Grouped, desktop: a sticky rail meant to sit beside the content.
  //    Collapsed, it's a strip of icons — one per section — so it stays
  //    out of the content's way; clicking one expands the rail and
  //    brings that section's full tab list into view. ──
  if (!isMobile) {
    if (railCollapsed) {
      return (
        <nav className={`tabbar-rail tabbar-rail-collapsed no-print ${className}`} aria-label="Sections">
          <button
            type="button"
            className="tabbar-rail-toggle"
            onClick={() => setRailCollapsed(false)}
            aria-label="Expand sections"
            title="Expand sections"
          >
            <Icon name="next" size={18} />
          </button>
          {effectiveGroups.map((g, i) => {
            const isActiveGroup = i === activeGroupIndex;
            return (
              <button
                key={g.label}
                type="button"
                className={`tabbar-rail-icon panel-fade-in${isActiveGroup ? ' is-active' : ''}`}
                title={g.label}
                aria-label={g.label}
                onClick={() => {
                  pendingGroupScroll.current = i;
                  setRailCollapsed(false);
                }}
              >
                {g.icon ? <Icon name={g.icon} size={20} /> : (g.label || '?').charAt(0)}
              </button>
            );
          })}
        </nav>
      );
    }
    return (
      <nav ref={railRef} className={`tabbar-rail no-print ${className}`} aria-label="Sections">
        <button
          type="button"
          className="tabbar-rail-toggle"
          onClick={() => setRailCollapsed(true)}
          aria-label="Collapse sections"
          title="Collapse sections"
        >
          <Icon name="back" size={18} />
        </button>
        {effectiveGroups.map((g, i) => (
          <div key={g.label} className="panel-fade-in" ref={el => { groupRefs.current[i] = el; }}>
            <div className="tabbar-rail-group-label">
              {g.icon && <Icon name={g.icon} size={16} />} {g.label}
            </div>
            {g.tabs.map(t => (
              <ListItem
                key={t.id}
                t={t}
                isActive={activeTab === t.id}
                onChange={onChange}
                tabRef={el => { tabRefs.current[t.id] = el; }}
              />
            ))}
          </div>
        ))}
      </nav>
    );
  }

  // Unreachable: flatMode || isMobile above already returns for every
  // mobile case, grouped or not — the only remaining path here is
  // grouped + desktop, handled above. (No mobile-specific branch left:
  // that's the point — mobile no longer has a layout of its own to
  // maintain separately from flat mode's.)
  return null;
}

/* ── styles (layout-only; visual language lives in index.css so both
     breakpoints and both nav shapes share one definition) ── */

const scrollRowOuter = { position: 'relative', display: 'flex', alignItems: 'stretch', minWidth: 0 };
const scrollRowInner = { display: 'flex', flexWrap: 'wrap', rowGap: '10px', columnGap: '6px', alignItems: 'stretch', minWidth: 0, flex: 1 };
// Used whenever the row must scroll horizontally regardless of viewport
// width — driven by the same isMobile JS check the rest of TabBar uses,
// instead of a separate max-width media query that can drift out of sync
// with it (see the .dash-body comment above for the bug that caused).
const scrollRowInnerForced = {
  ...scrollRowInner,
  flexWrap: 'nowrap',
  overflowX: 'auto',
  WebkitOverflowScrolling: 'touch',
};
const arrowBtn = {
  position: 'absolute', top: 0, bottom: 0, zIndex: 2, width: '26px', border: 'none',
  background: 'linear-gradient(to right, var(--bg-color) 60%, transparent)',
  color: 'var(--text-color)', cursor: 'pointer', fontSize: '18px', fontWeight: 700, lineHeight: 1,
};
const countPillStyle = { fontSize: '11px', backgroundColor: 'var(--border-color)', borderRadius: '10px', padding: '1px 7px', fontWeight: '700' };
