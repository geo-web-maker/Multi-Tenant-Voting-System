import React, { useCallback, useEffect, useRef, useState } from 'react';
import api, { getErrorMessage } from '../api';
import { getCurrentPage, onPageChange } from '../analytics';

const deviceFor = (w) => (w < 768 ? 'mobile' : w < 1100 ? 'tablet' : 'desktop');

// The element that actually scrolls (window, or an inner dashboard container), as the tracker measures it.
function findScroller() {
  const el = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const oy = getComputedStyle(n).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight) return n;
  }
  return null;
}

// Translucent, non-interactive canvas. `embedded` = inside the modal iframe (always on, no toggle).
export default function HeatmapOverlay({ page, embedded = false }) {
  const [current, setCurrent] = useState(page || getCurrentPage());
  const [open, setOpen] = useState(embedded);
  const [kind, setKind] = useState('click');
  const [device, setDevice] = useState(() => deviceFor(window.innerWidth));
  const [cells, setCells] = useState([]);
  const [error, setError] = useState('');
  const canvas = useRef(null);
  const scroller = useRef(null);
  const role = sessionStorage.getItem('admin_role');
  const allowed = embedded || role === 'superadmin' || Boolean(sessionStorage.getItem('view_as'));

  useEffect(() => (page ? undefined : onPageChange(setCurrent)), [page]);
  useEffect(() => {
    if (!allowed || !open || !current) return undefined;
    let live = true;
    api.get('/superadmin/analytics/heatmap', { params: { page: current, kind, device, seg: 'all' } })
      .then((r) => { if (live) { setCells(r.data); setError(''); } })
      .catch((e) => { if (live) { setCells([]); setError(getErrorMessage(e, 'Heatmap data is not available in this session.')); } });
    return () => { live = false; };
  }, [allowed, open, current, kind, device]);

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = window.innerWidth * dpr; c.height = window.innerHeight * dpr;
    const g = c.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, window.innerWidth, window.innerHeight);
    const sc = scroller.current;
    const top = sc ? sc.scrollTop : window.scrollY;
    const offset = sc ? sc.getBoundingClientRect().top : 0;
    const style = getComputedStyle(document.documentElement);
    const color = style.getPropertyValue('--danger').trim() || getComputedStyle(document.body).color;
    g.fillStyle = color; g.strokeStyle = color;
    const max = Math.max(1, ...cells.map((x) => x.n));
    if (kind === 'click') {
      cells.forEach((cell) => {
        const x = (cell.gx / 50) * window.innerWidth;
        const y = cell.gy * 20 + 10 - top + offset;
        if (y < -30 || y > window.innerHeight + 30) return;
        g.globalAlpha = Math.min(0.75, 0.15 + (cell.n / max) * 0.6);
        g.beginPath(); g.arc(x, y, 14, 0, Math.PI * 2); g.fill();
      });
    } else {
      const total = cells.reduce((a, x) => a + x.n, 0) || 1;
      const height = sc ? sc.scrollHeight : document.documentElement.scrollHeight;
      g.font = '12px sans-serif';
      for (let step = 0; step < 10; step++) {
        const reach = cells.filter((x) => x.gy >= step).reduce((a, x) => a + x.n, 0) / total;
        const y = (step / 10) * height - top + offset;
        g.globalAlpha = 0.08 + reach * 0.4;
        g.fillRect(0, y, window.innerWidth, (height / 10));
        g.globalAlpha = 0.9;
        g.fillText(`${step * 10}%: ${Math.round(reach * 100)}% reached`, 8, y + 16);
      }
    }
  }, [cells, kind]);

  useEffect(() => {
    if (!allowed || !open) return undefined;
    scroller.current = findScroller();
    let raf = 0;
    const schedule = (e) => {
      if (e?.type === 'scroll' && e.target instanceof Element && e.target !== document.documentElement) scroller.current = e.target;
      cancelAnimationFrame(raf); raf = requestAnimationFrame(draw);
    };
    schedule();
    window.addEventListener('resize', schedule);
    document.addEventListener('scroll', schedule, { capture: true, passive: true });
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', schedule); document.removeEventListener('scroll', schedule, true); };
  }, [allowed, open, draw]);

  if (!allowed) return null;
  return (
    <div data-no-track>
      {open && <canvas ref={canvas} aria-hidden="true" style={{ position: 'fixed', inset: 0, width: '100vw', height: '100vh', pointerEvents: 'none', zIndex: 9990 }} />}
      {open && !embedded && (
        <div style={{ ...panel, right: 12, bottom: 'calc(68px + env(safe-area-inset-bottom))' }}>
          <select aria-label="Heatmap type" value={kind} onChange={(e) => setKind(e.target.value)} style={field}>
            <option value="click">Clicks</option><option value="scroll">Scroll depth</option>
          </select>
          <select aria-label="Device" value={device} onChange={(e) => setDevice(e.target.value)} style={field}>
            <option value="mobile">Mobile</option><option value="tablet">Tablet</option><option value="desktop">Desktop</option>
          </select>
          <p style={note}>{error || `Page: ${current || 'unknown'}. Vertical positions may drift slightly when page length changes.`}</p>
        </div>
      )}
      {!embedded && (
        <button type="button" onClick={() => setOpen((v) => !v)} aria-pressed={open} style={toggle}>
          {open ? 'Hide heatmap' : 'Heatmap'}
        </button>
      )}
      {embedded && error && <p style={{ ...note, ...panel, top: 8, left: 8, right: 'auto', bottom: 'auto' }}>{error}</p>}
    </div>
  );
}

const toggle = {
  position: 'fixed', right: 12, bottom: 'calc(12px + env(safe-area-inset-bottom))', zIndex: 9999, minWidth: 44, minHeight: 44,
  padding: '0 14px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)',
  color: 'var(--text-color)', fontWeight: 700, fontSize: 13, cursor: 'pointer',
};
const panel = {
  position: 'fixed', zIndex: 9999, width: 220, maxWidth: 'calc(100vw - 24px)', padding: 10, borderRadius: 12,
  border: '1px solid var(--border-color)', background: 'var(--card-bg)', display: 'grid', gap: 8,
};
const field = { minHeight: 44, padding: '8px 10px', border: '1px solid var(--border-color)', borderRadius: 8, background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13 };
const note = { margin: 0, fontSize: 12, color: 'var(--text-muted)', overflowWrap: 'anywhere' };
