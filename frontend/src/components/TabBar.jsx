import React, { useCallback, useEffect, useRef, useState } from 'react';

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
//            renders one scrollable row of group pills, and below it a
//            plain vertical list of the selected group's tabs (same list
//            item as the desktop rail) — only the group row ever scrolls
//            horizontally.
//
// Grouped + desktop returns a self-contained <nav> meant to sit beside
// the page's content, not above it — wrap both in a `.dash-body` flex
// row (`.dash-main` on the content column) so it lays out as a rail on
// desktop and stacks on mobile without any JS breakpoint duplication.

const MOBILE_QUERY = '(max-width: 768px)';

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
function ScrollRow({ children, rowClassName = '', showArrows = false, innerRef }) {
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
        style={scrollRowInner}
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
      className={`tabbar-pill${isActive ? ' is-active' : ''}`}
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
      className={`tabbar-list-item${isActive ? ' is-active' : ''}`}
    >
      <span>{t.label}</span>
      {t.count !== undefined && t.count !== null && <span style={countPillStyle}>{t.count}</span>}
    </button>
  );
}

export default function TabBar({ tabs, groups, activeTab, onChange, className = '' }) {
  const isMobile = useIsMobile();
  const flatMode = !groups || groups.length === 0;
  const effectiveGroups = flatMode ? [{ label: null, tabs: tabs || [] }] : groups;

  const activeGroupIndex = Math.max(0, effectiveGroups.findIndex(g => g.tabs.some(t => t.id === activeTab)));
  const [selectedGroupIdx, setSelectedGroupIdx] = useState(activeGroupIndex);
  useEffect(() => {
    setSelectedGroupIdx(activeGroupIndex);
  }, [activeGroupIndex]);

  const tabRefs = useRef({});
  const groupRefs = useRef({});

  // Auto-scroll the active tab (and, on mobile, its group pill) into view
  // whenever activeTab changes — including on first load.
  useEffect(() => {
    tabRefs.current[activeTab]?.scrollIntoView?.({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }, [activeTab, isMobile, selectedGroupIdx]);
  useEffect(() => {
    if (isMobile) {
      groupRefs.current[selectedGroupIdx]?.scrollIntoView?.({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
  }, [selectedGroupIdx, isMobile]);

  // ── Flat mode: one row, wraps on desktop, scrolls on mobile ──
  if (flatMode) {
    return (
      <ScrollRow rowClassName={`tab-scroll no-print ${className}`} showArrows={!isMobile}>
        {effectiveGroups[0].tabs.map(t => (
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

  // ── Grouped, desktop: a sticky rail meant to sit beside the content ──
  if (!isMobile) {
    return (
      <nav className={`tabbar-rail no-print ${className}`} aria-label="Sections">
        {effectiveGroups.map(g => (
          <div key={g.label}>
            <div className="tabbar-rail-group-label">{g.label}</div>
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

  // ── Grouped, mobile: one scrollable row of group pills, then a plain
  //    vertical list of that group's tabs — only the group row scrolls. ──
  const selectedGroup = effectiveGroups[selectedGroupIdx] || effectiveGroups[0];
  return (
    <div className={`tabbar-mobile-groups no-print ${className}`} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <ScrollRow rowClassName="tab-scroll tabbar-group-row">
        {effectiveGroups.map((g, i) => (
          <button
            key={g.label}
            ref={el => { groupRefs.current[i] = el; }}
            onClick={() => setSelectedGroupIdx(i)}
            className={`tabbar-pill${i === selectedGroupIdx ? ' is-active' : ''}`}
          >
            {g.label}
          </button>
        ))}
      </ScrollRow>
      <div className="tabbar-mobile-list">
        {selectedGroup.tabs.map(t => (
          <ListItem
            key={t.id}
            t={t}
            isActive={activeTab === t.id}
            onChange={onChange}
            tabRef={el => { tabRefs.current[t.id] = el; }}
          />
        ))}
      </div>
    </div>
  );
}

/* ── styles (layout-only; visual language lives in index.css so both
     breakpoints and both nav shapes share one definition) ── */

const scrollRowOuter = { position: 'relative', display: 'flex', alignItems: 'stretch', minWidth: 0 };
const scrollRowInner = { display: 'flex', flexWrap: 'wrap', rowGap: '10px', columnGap: '6px', alignItems: 'stretch', minWidth: 0, flex: 1 };
const arrowBtn = {
  position: 'absolute', top: 0, bottom: 0, zIndex: 2, width: '26px', border: 'none',
  background: 'linear-gradient(to right, var(--bg-color) 60%, transparent)',
  color: 'var(--text-color)', cursor: 'pointer', fontSize: '18px', fontWeight: 700, lineHeight: 1,
};
const countPillStyle = { fontSize: '11px', backgroundColor: 'var(--border-color)', borderRadius: '10px', padding: '1px 7px', fontWeight: '700' };
