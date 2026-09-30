import { API_BASE, ORG_SLUG, SUPERADMIN_ORG_OVERRIDE_KEY } from './api';

// Privacy: random per-tab id only. Never sends URLs, ids, names, text, IPs or error messages.
const SID_KEY = 'an_sid';
const PAGES_KEY = 'an_pages';
const COUNT_KEY = 'an_pv_count';
const PERF_KEY = 'an_perf_sent';
const IN_HEATMAP_FRAME = (() => { try { return new URLSearchParams(window.location.search).has('heatmap'); } catch { return false; } })();

let currentPage = null;
let visibleSince = 0;
let visibleMs = 0; // visible time on the current page NOT yet reported
let queue = [];
let backoffUntil = 0;
let initialized = false;
let scrollStep = -1;
let lastScrollAt = 0;
let recentClicks = [];
let pageLoaded = false;
let firstApiMs = null;
const listeners = new Set();

// Evaluated on every call so a session that becomes "View as" or opts out later stops sending.
function allowed() {
  try {
    return !IN_HEATMAP_FRAME && !sessionStorage.getItem('view_as')
      && navigator.doNotTrack !== '1' && !navigator.globalPrivacyControl;
  } catch { return false; }
}
function sid() {
  let v = sessionStorage.getItem(SID_KEY);
  if (!v) { v = crypto.randomUUID(); sessionStorage.setItem(SID_KEY, v); }
  return v;
}
function slug() { return sessionStorage.getItem(SUPERADMIN_ORG_OVERRIDE_KEY) || ORG_SLUG; }
const visible = () => document.visibilityState === 'visible';

export function pageName(view, step) {
  if (view === 'voter') return ({ 1: 'voter_identity', 1.5: 'voter_otp', 2: 'voter_otp', 3: 'voter_ballot' })[step] || null;
  if (view === 'results') return 'results';
  if (view === 'apply') return 'apply';
  return null; // dashboards are named <role>:<tab> by TabBar
}

function enqueue(event) {
  if (!allowed() || !event.page) return;
  queue.push(event);
  if (queue.length > 50) queue.splice(0, queue.length - 50);
}

function flush() {
  if (!allowed() || !queue.length || Date.now() < backoffUntil) return;
  const events = queue.splice(0, 25);
  const body = JSON.stringify({ sid: sid(), w: window.innerWidth, seg: sessionStorage.getItem('admin_role') ? 'staff' : 'public', events });
  const fail = () => { backoffUntil = Date.now() + 120000; queue = events.concat(queue).slice(-50); };
  try {
    fetch(`${API_BASE}/analytics/collect`, {
      method: 'POST', keepalive: true,
      headers: { 'Content-Type': 'application/json', ...(slug() ? { 'X-Org-Slug': slug() } : {}) }, body,
    }).then((r) => { if (!r.ok) fail(); }).catch(fail);
  } catch { fail(); }
}

// Report visible time not yet reported, then reset so no millisecond is counted twice.
function takeUnreportedMs() {
  if (visibleSince) { visibleMs += performance.now() - visibleSince; visibleSince = visible() ? performance.now() : 0; }
  const ms = Math.min(1800000, Math.round(visibleMs));
  visibleMs = 0;
  return ms;
}
function leaveCurrent() {
  if (!currentPage) return;
  const dur = takeUnreportedMs();
  if (dur > 0) enqueue({ t: 'leave', page: currentPage, dur });
}

export function trackPage(name) {
  if (!name || name === currentPage) return;
  const fromDur = currentPage ? takeUnreportedMs() : 0;
  currentPage = name;
  visibleMs = 0; visibleSince = visible() ? performance.now() : 0; scrollStep = -1;
  listeners.forEach((cb) => cb(currentPage));
  if (!allowed()) return;
  let pages = [];
  try { pages = JSON.parse(sessionStorage.getItem(PAGES_KEY) || '[]'); } catch { pages = []; }
  const count = Number(sessionStorage.getItem(COUNT_KEY) || '0');
  enqueue({
    t: 'pv', page: name, from: pages.length ? pages[pages.length - 1] : '(entry)', from_dur: fromDur,
    first: count === 0, ns: count === 0, second: count === 1, entry: pages[0] || name,
  });
  pages.push(name);
  sessionStorage.setItem(PAGES_KEY, JSON.stringify(pages.slice(-50)));
  sessionStorage.setItem(COUNT_KEY, String(count + 1));
  maybeSendPerf();
}
export const getCurrentPage = () => currentPage;
export function onPageChange(cb) { listeners.add(cb); return () => listeners.delete(cb); }

function entryPage() {
  try { return JSON.parse(sessionStorage.getItem(PAGES_KEY) || '[]')[0] || currentPage; } catch { return currentPage; }
}
function maybeSendPerf(force = false) {
  if (!allowed() || !pageLoaded || sessionStorage.getItem(PERF_KEY) || !entryPage()) return;
  if (firstApiMs === null && !force) return;
  sessionStorage.setItem(PERF_KEY, '1');
  const nav = performance.getEntriesByType('navigation')[0];
  enqueue({
    t: 'perf', page: entryPage(), load_ms: Math.round(nav?.loadEventEnd || 0), first_api_ms: Math.round(firstApiMs || 0),
    net: navigator.connection?.effectiveType || 'unknown',
  });
}

function scrollParent(el) {
  for (let n = el; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const oy = getComputedStyle(n).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight) return n;
  }
  return null;
}
const INTERACTIVE = 'a,button,input,select,textarea,label,summary,[role="button"],[role="tab"],[role="link"],[data-track]';

function onClick(e) {
  const target = e.target instanceof Element ? e.target : null;
  if (!currentPage || !target || target.closest('[data-no-track]')) return;
  const tracked = target.closest('[data-track]');
  const label = tracked?.getAttribute('data-track') || target.tagName.toLowerCase();
  if (!/^[a-z0-9_-]{2,40}$/.test(label)) return;
  const now = performance.now();
  recentClicks = recentClicks.filter((c) => now - c.t < 1000);
  recentClicks.push({ t: now, x: e.clientX, y: e.clientY });
  const rage = recentClicks.length >= 3 && recentClicks.every((c) => Math.hypot(c.x - e.clientX, c.y - e.clientY) <= 30);
  const dead = !target.closest(INTERACTIVE) && getComputedStyle(target).cursor !== 'pointer' && !window.getSelection()?.toString();
  const sc = scrollParent(target);
  const pageY = sc ? e.clientY - sc.getBoundingClientRect().top + sc.scrollTop : e.clientY + window.scrollY;
  const width = Math.max(1, document.documentElement.clientWidth);
  enqueue({
    t: 'click', page: currentPage, label, dead, rage,
    gx: Math.max(0, Math.min(49, Math.round((e.clientX / width) * 50))),
    gy: Math.max(0, Math.min(400, Math.floor(pageY / 20))),
  });
}

function onScroll(e) {
  const now = Date.now();
  if (!currentPage || !visible() || now - lastScrollAt < 250) return;
  lastScrollAt = now;
  const el = e.target instanceof Element ? e.target : document.documentElement;
  const top = el === document.documentElement ? window.scrollY : el.scrollTop;
  const max = Math.max(1, (el === document.documentElement ? el.scrollHeight - window.innerHeight : el.scrollHeight - el.clientHeight));
  const step = Math.min(10, Math.floor((top / max) * 10));
  if (step > scrollStep) { scrollStep = step; enqueue({ t: 'scroll', page: currentPage, pct: step * 10 }); }
}

export function initAnalytics() {
  if (initialized) return;
  initialized = true;
  if (!allowed()) return;
  sid();
  setInterval(flush, 30000);
  document.addEventListener('visibilitychange', () => {
    if (visible()) { visibleSince = performance.now(); return; }
    leaveCurrent(); visibleSince = 0; flush();
  });
  window.addEventListener('pagehide', () => { leaveCurrent(); flush(); }, { capture: true });
  document.addEventListener('click', onClick, true);
  document.addEventListener('scroll', onScroll, { capture: true, passive: true });
  const err = (name) => enqueue({ t: 'err', page: currentPage, name });
  window.addEventListener('error', (e) => err(e?.error?.constructor?.name || 'Error'));
  window.addEventListener('unhandledrejection', (e) => err(e?.reason?.constructor?.name || 'Error'));
  window.addEventListener('an:api', (e) => { if (firstApiMs === null) { firstApiMs = Number(e.detail?.ms) || 0; maybeSendPerf(); } });
  window.addEventListener('an:netfail', (e) => err(e.detail?.kind === 'timeout' ? 'net:timeout' : 'net:network'));
  const onLoaded = () => { pageLoaded = true; maybeSendPerf(); setTimeout(() => maybeSendPerf(true), 15000); };
  if (document.readyState === 'complete') setTimeout(onLoaded, 0);
  else window.addEventListener('load', () => setTimeout(onLoaded, 0), { once: true }); // loadEventEnd is set after load handlers
}
