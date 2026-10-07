// Console navigation (BP-T7a). Takes the SAME props as the default TabBar (`tabs` | `groups`, `activeTab`, `onChange`,
// `className`) and calls the same handlers. Layout is CSS-only at 768 px (F7): a sticky rail on desktop, a pill row on phones.
// It also publishes the active "group / tab" to the chrome store so the sticky header can show it as a crumb (no prop drilling).
import { useEffect, useMemo, useRef } from 'react';
import { trackPage } from '../../analytics';
import { setChrome, useChrome } from '../../templateChrome';
import { textOf } from './labels.js';

// Same analytics call as the default TabBar (role:tab from the admin session). Kept in sync by hand: 3 lines.
function useTabAnalytics(activeTab) {
  useEffect(() => {
    const role = sessionStorage.getItem('admin_role');
    if (role && activeTab) trackPage(`${role}:${String(activeTab).toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 40)}`);
  }, [activeTab]);
}

// Brings the active item into view inside the nav ONLY (never the browser's scrollIntoView: it can shift the whole page, see TabBar).
function useKeepActiveVisible(navRef, activeTab) {
  useEffect(() => {
    const nav = navRef.current;
    const el = nav?.querySelector('[aria-current="page"]');
    if (!nav || !el) return;
    if (nav.scrollWidth > nav.clientWidth) {
      nav.scrollLeft = Math.max(0, el.offsetLeft - (nav.clientWidth - el.offsetWidth) / 2);
    } else if (nav.scrollHeight > nav.clientHeight) {
      const top = el.offsetTop;
      if (top < nav.scrollTop || top + el.offsetHeight > nav.scrollTop + nav.clientHeight) {
        nav.scrollTop = Math.max(0, top - (nav.clientHeight - el.offsetHeight) / 2);
      }
    }
  }, [navRef, activeTab]);
}

function Item({ t, active, onChange }) {
  const hasCount = t.count !== undefined && t.count !== null;
  return (
    <button
      type="button" data-track={`tab-${t.id}`} onClick={() => onChange(t.id)}
      aria-current={active ? 'page' : undefined} className={active ? 'bp-on' : undefined}
    >
      {t.label}
      {hasCount && <span className="bp-ct">{t.count}</span>}
    </button>
  );
}

export default function ConsoleSidebar({ tabs, groups, activeTab, onChange, className = '' }) {
  const flat = !groups || groups.length === 0;
  const { role, onLogout } = useChrome();
  const navRef = useRef(null);

  const eff = useMemo(() => (flat ? [{ label: role || '', tabs: tabs || [] }] : groups), [flat, role, tabs, groups]);
  const all = useMemo(() => eff.flatMap((g) => g.tabs), [eff]);
  const idx = all.findIndex((t) => t.id === activeTab);
  const activeGroup = idx >= 0 ? eff.find((g) => g.tabs.some((t) => t.id === activeTab)) : null;
  const groupText = activeGroup ? textOf(activeGroup.label) : '';
  const tabText = idx >= 0 ? textOf(all[idx].label) : '';
  const count = all.length;

  useEffect(() => {
    setChrome({ group: groupText, tab: tabText, tabIndex: idx + 1, tabCount: count });
  }, [groupText, tabText, idx, count]);
  // Clear only what this component published; the toolbar owns `onLogout`, the header owns `role`.
  useEffect(() => () => setChrome({ group: '', tab: '', tabIndex: 0, tabCount: 0 }), []);

  useTabAnalytics(activeTab);
  useKeepActiveVisible(navRef, activeTab);

  if (flat) {
    return (
      <nav ref={navRef} className={`bp-side bp-flat no-print ${className}`.trim()} aria-label="Sections">
        {all.map((t) => <Item key={t.id} t={t} active={activeTab === t.id} onChange={onChange} />)}
      </nav>
    );
  }

  return (
    <nav ref={navRef} className={`bp-side no-print ${className}`.trim()} aria-label="Sections">
      {eff.map((g, i) => (
        <div key={textOf(g.label) || i} className="bp-grp" role="group" aria-label={textOf(g.label)}>
          <div className="bp-grp-l" aria-hidden="true">{g.label}</div>
          {g.tabs.map((t) => <Item key={t.id} t={t} active={activeTab === t.id} onChange={onChange} />)}
        </div>
      ))}
      {onLogout && (
        <div className="bp-grp bp-sess" role="group" aria-label="Session">
          <div className="bp-grp-l" aria-hidden="true">Session</div>
          <button type="button" onClick={onLogout}>Log out</button>
        </div>
      )}
    </nav>
  );
}
