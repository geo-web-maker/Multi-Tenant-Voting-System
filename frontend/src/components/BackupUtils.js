import { fmtZoned, DEFAULT_TZ } from '../tz';

export const muted = { color: 'var(--text-muted)', fontSize: 13, margin: '6px 0 0' };
export const h3 = { margin: '0 0 10px', fontSize: 15 };
export const safeTime = (v) => v ? fmtZoned(v, DEFAULT_TZ) : '—';
export const bytesText = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
};
export const durationText = (s) => Number.isFinite(Number(s)) ? `${Number(s).toFixed(Number(s) < 10 ? 1 : 0)} s` : '—';
export const statusOf = (raw) => {
  const s = String(raw || '').toLowerCase();
  if (['healthy', 'ok', 'passed', 'valid', 'enabled'].includes(s)) return 'passed';
  if (['warning', 'slow', 'busy'].includes(s)) return 'warning';
  if (['critical', 'down', 'failed', 'invalid'].includes(s)) return 'failed';
  if (['running', 'queued'].includes(s)) return 'running';
  if (['skipped'].includes(s)) return 'skipped';
  return 'neutral';
};
export const statusLabel = (raw) => {
  const s = String(raw || '').toLowerCase();
  if (!s || ['not run', 'never', 'unknown'].includes(s)) return 'Not run';
  if (['ok', 'healthy', 'passed', 'valid', 'enabled'].includes(s)) return 'Healthy';
  if (['warning', 'slow', 'busy'].includes(s)) return 'Warning';
  if (['critical', 'down', 'failed', 'invalid'].includes(s)) return 'Failed';
  if (['running', 'queued'].includes(s)) return s === 'queued' ? 'Queued' : 'Running';
  if (s === 'skipped') return 'Skipped';
  if (['disabled', 'unconfigured'].includes(s)) return 'Not configured';
  return String(raw).replaceAll('_', ' ');
};

// One card and one tile for both templates. Blueprint only re-tones .perf-card / .perf-tile (blueprint.css, "PANEL KIT"): panels sit
// inside the console shell, which is already the accent-topped card, so a second bp-card here would nest accent borders.
export const cardClass = () => 'perf-card card-pad';
export const tileClass = () => 'perf-card card-pad perf-tile';

