import React, { useCallback, useEffect, useRef, useState } from 'react';

// Shared tab-bar component used by every admin dashboard.
//
// Usage:
//   <TabBar tabs={flatTabs} activeTab={activeTab} onChange={setActiveTab} />
//   <TabBar groups={groupedTabs} activeTab={activeTab} onChange={setActiveTab} />
//
// `tabs`   — flat list of { id, label, count? }. Renders exactly like the old
//            per-dashboard tab bar (desktop wraps, mobile scrolls), just with
//            drag-to-scroll + edge fades thrown in for free.
// `groups` — [{ label, tabs: [...] }]. On desktop, each group renders as a
//            section header above its own row of tabs (everything visible).
//            On mobile, a row of group names is shown; tapping one reveals
//            that group's tabs in a second row below. Whichever group holds
//            the current activeTab is auto-selected and scrolled into view.

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

// A horizontally-scrollable row: click-and-drag to scroll, edge fades that
// only show when there's actually more content that way, and (optionally)
// arrow buttons at each end. Shift + mouse-wheel scrolling needs no JS at
// all — browsers do that for free on any overflow-x: auto element.
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

  // Auto-scroll the active tab (and, on mobile, its group button) into view
  // whenever activeTab changes — including on first load.
  useEffect(() => {
    tabRefs.current[activeTab]?.scrollIntoView?.({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }, [activeTab, isMobile, selectedGroupIdx]);
  useEffect(() => {
    if (isMobile) {
      groupRefs.current[selectedGroupIdx]?.scrollIntoView?.({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
  }, [selectedGroupIdx, isMobile]);

  function renderTabButton(t) {
    return (
      <button
        key={t.id}
        ref={el => { tabRefs.current[t.id] = el; }}
        onClick={() => onChange(t.id)}
        style={{ ...tabBtnStyle, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}
      >
        {t.label}
        {t.count !== undefined && t.count !== null && <span style={countPillStyle}>{t.count}</span>}
      </button>
    );
  }

  if (flatMode) {
    return (
      <ScrollRow rowClassName={`tab-scroll no-print ${className}`} showArrows={!isMobile}>
        {effectiveGroups[0].tabs.map(renderTabButton)}
      </ScrollRow>
    );
  }

  if (!isMobile) {
    return (
      <div className={`tabbar-desktop-groups no-print ${className}`} style={desktopGroupsWrap}>
        {effectiveGroups.map(g => (
          <div key={g.label} style={desktopGroupBlock}>
            <div style={desktopGroupHeader}>{g.label}</div>
            <div style={desktopGroupTabs}>
              {g.tabs.map(renderTabButton)}
            </div>
          </div>
        ))}
      </div>
    );
  }

  const selectedGroup = effectiveGroups[selectedGroupIdx] || effectiveGroups[0];
  return (
    <div className={`tabbar-mobile-groups no-print ${className}`}>
      <ScrollRow rowClassName="tabbar-group-row">
        {effectiveGroups.map((g, i) => (
          <button
            key={g.label}
            ref={el => { groupRefs.current[i] = el; }}
            onClick={() => setSelectedGroupIdx(i)}
            style={{ ...groupBtnStyle, ...(i === selectedGroupIdx ? groupBtnActiveStyle : null) }}
          >
            {g.label}
          </button>
        ))}
      </ScrollRow>
      <ScrollRow rowClassName="tab-scroll">
        {selectedGroup.tabs.map(renderTabButton)}
      </ScrollRow>
    </div>
  );
}

/* ── styles ── */

const scrollRowOuter = { position: 'relative', display: 'flex', alignItems: 'stretch', minWidth: 0 };
const scrollRowInner = { display: 'flex', flexWrap: 'wrap', rowGap: '10px', columnGap: '4px', alignItems: 'stretch', minWidth: 0, flex: 1 };
const arrowBtn = {
  position: 'absolute', top: 0, bottom: 0, zIndex: 2, width: '26px', border: 'none',
  background: 'linear-gradient(to right, var(--bg-color) 60%, transparent)',
  color: 'var(--text-color)', cursor: 'pointer', fontSize: '18px', fontWeight: 700, lineHeight: 1,
};
const tabBtnStyle = {
  background: 'none', border: 'none', padding: '10px 14px', cursor: 'pointer', fontWeight: '600',
  color: 'var(--text-color)', fontSize: '13px', lineHeight: '1.3', borderRadius: '6px 6px 0 0',
  display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap',
};
const countPillStyle = { fontSize: '11px', backgroundColor: 'var(--border-color)', borderRadius: '10px', padding: '1px 7px', fontWeight: '700' };

const desktopGroupsWrap = { display: 'flex', flexWrap: 'wrap', gap: '20px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', paddingBottom: '4px' };
const desktopGroupBlock = { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 };
const desktopGroupHeader = { fontSize: '10px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-muted)', padding: '0 2px 4px' };
const desktopGroupTabs = { display: 'flex', flexWrap: 'wrap', rowGap: '6px', columnGap: '4px' };

const groupBtnStyle = {
  background: 'var(--surface-2)', border: 'none', padding: '6px 13px', borderRadius: '14px', cursor: 'pointer',
  fontWeight: '700', fontSize: '11px', color: 'var(--text-color)', whiteSpace: 'nowrap', opacity: 0.7,
};
const groupBtnActiveStyle = { background: 'var(--success)', color: '#fff', opacity: 1 };
