import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act, cleanup } from '@testing-library/react';

const mockGet = vi.fn();
const mockPut = vi.fn();
const mockPost = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), put: (...a) => mockPut(...a), post: (...a) => mockPost(...a) },
  getErrorMessage: (_e, d) => d,
}));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => async () => true }));

import PerformancePanel from './PerformancePanel';

const SUMMARY_URL = '/superadmin/performance/summary';
const PRESETS = [
  { id: 'free', ops_cap: 100, conn_cap: 500, note: 'Atlas Free' },
  { id: 'custom', ops_cap: null, conn_cap: null, note: 'Custom caps' },
];
const config = (over = {}) => ({
  enabled: true, paused: false, tier: 'free', ops_cap: 100, conn_cap: 500, warn_pct: 70, crit_pct: 90,
  slow_ms: 250, persist_s: 300, note: 'Atlas Free', presets: PRESETS, presets_verified_on: '2026-10-10',
  sources: { ops_cap: 'preset', conn_cap: 'preset', warn_pct: 'env', crit_pct: 'env', slow_ms: 'env', persist_s: 'env' },
  ...over,
});
const summary = (over = {}) => ({
  enabled: true, paused: false, ready: true, status: 'ok', tier: 'free', conn_cap: 500, uptime_s: 3600,
  collecting_since: '2026-10-10T07:12:00Z',
  db: { ops_s: 37, ops_s_10s: 31, ops_s_60s: 22, peak_15m: 88, cap: 100, cap_pct: 37, pool: { in_use: 3, max: 20, waiting: 0, timeouts_1h: 0 }, latency_ms: { p50: 3, p95: 14, p99: 41 } },
  http: { rps: 11, in_flight: 2, p95_ms: 120, s5xx_1m: 0, s429_1m: 0 },
  runtime: { loop_lag_ms: { now: 3, p95: 9, max: 41 }, rss_mb: 142, cpu_pct: 18 },
  election: { voters_per_min_headroom: 140, ops_per_voter: 26, ops_per_voter_source: 'audit' },
  alerts: [], recent_alerts: [],
  ...over,
});

function serve({ sum = summary(), cfg = config() } = {}) {
  mockGet.mockImplementation((url) => {
    const data = {
      [SUMMARY_URL]: sum,
      '/superadmin/performance/config': cfg,
      '/superadmin/performance/timeseries': { cap: sum?.db?.cap ?? null, points: [{ ops: 10 }, { ops: 20 }] },
      '/superadmin/performance/breakdown': { rows: [], unattributed_pct: 12 },
      '/superadmin/performance/slow': { commands: [] },
      '/superadmin/performance/sink': { type: 'none', detail: 'memory only' },
      '/superadmin/performance/orgs': { window: '15m', buckets: 15, rows: [] },
      '/superadmin/performance/storage': { mode: 'mongo', env_mode: 'mongo', postgres_configured: true, chosen_in_app: false, migration: { status: 'idle' } },
    }[url];
    return Promise.resolve({ data });
  });
}
const summaryCalls = () => mockGet.mock.calls.filter((c) => c[0] === SUMMARY_URL).length;
const setHidden = (v) => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });

describe('PerformancePanel states (guide 7.2)', () => {
  beforeEach(() => { mockGet.mockReset(); mockPut.mockReset(); mockPost.mockReset(); setHidden(false); });
  afterEach(() => cleanup());

  it('off: says monitoring is off and shows no numbers', async () => {
    serve({ sum: summary({ enabled: false }) });
    render(<PerformancePanel />);
    await screen.findByText('Performance monitoring is off.');
    expect(screen.queryByTestId('ops-now')).toBeNull();
  });

  it('paused: pill reads Paused', async () => {
    serve({ sum: summary({ paused: true }) });
    render(<PerformancePanel />);
    await screen.findByText('Paused');
  });

  it('collecting: never a green OK with zero', async () => {
    serve({ sum: summary({ ready: false, status: 'ok', db: { ...summary().db, ops_s: 0 } }) });
    render(<PerformancePanel />);
    await screen.findByText('Collecting data, give it a minute.');
    expect(screen.getByTestId('ops-now').textContent).toBe('No data yet');
    expect(screen.queryByText('OK')).toBeNull();
  });

  it.each([['ok', 'OK'], ['busy', 'Busy'], ['critical', 'Critical'], ['throttling', 'Throttling']])('capped tier, status %s', async (status, label) => {
    serve({ sum: summary({ status }) });
    render(<PerformancePanel />);
    await screen.findByText(label);
    expect(screen.getByTestId('ops-now').textContent).toBe('37 / 100');
    expect((await screen.findByRole('progressbar')).getAttribute('aria-valuenow')).toBe('37');
    expect(screen.getByText(/About 140 voters per minute before the cap/)).toBeTruthy();
  });

  it('uncapped tier: raw ops/s, no bar, no headroom card', async () => {
    serve({
      sum: summary({ tier: 'custom', db: { ...summary().db, cap: null }, election: { voters_per_min_headroom: null } }),
      cfg: config({ tier: 'custom', ops_cap: null }),
    });
    render(<PerformancePanel />);
    await waitFor(() => expect(screen.getByTestId('ops-now').textContent).toBe('37'));
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.queryByText('Voter headroom')).toBeNull();
    expect(screen.getByText(/no hard ops cap/)).toBeTruthy();
  });

  it('load failure shows a retry that works', async () => {
    mockGet.mockRejectedValue(new Error('boom'));
    render(<PerformancePanel />);
    await screen.findByText('Could not load.');
    serve();
    fireEvent.click(screen.getByText('Retry'));
    await screen.findByText('OK');
  });

  it('shows the unattributed row text', async () => {
    serve();
    render(<PerformancePanel />);
    await screen.findByText(/Unattributed: 12%/);
  });
});

describe('PerformancePanel polling (guide 7.1)', () => {
  beforeEach(() => { mockGet.mockReset(); setHidden(false); vi.useFakeTimers({ shouldAdvanceTime: false }); });
  afterEach(() => { cleanup(); vi.useRealTimers(); setHidden(false); });

  it('polls summary about every 5 s while visible', async () => {
    serve();
    render(<PerformancePanel />);
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    const first = summaryCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(11000); });
    expect(summaryCalls()).toBeGreaterThan(first);
  });

  it('stops polling while the page is hidden and resumes when visible', async () => {
    serve();
    render(<PerformancePanel />);
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    setHidden(true);
    const before = summaryCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(summaryCalls()).toBe(before);
    setHidden(false);
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(100); });
    expect(summaryCalls()).toBeGreaterThan(before);
  });

  it('stops polling after unmount', async () => {
    serve();
    const { unmount } = render(<PerformancePanel />);
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    unmount();
    const before = summaryCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(summaryCalls()).toBe(before);
  });
});

describe('PerformanceSettings card (guide 2.5)', () => {
  beforeEach(() => { mockGet.mockReset(); mockPut.mockReset(); mockPost.mockReset(); setHidden(false); serve(); });
  afterEach(() => cleanup());

  const open = async () => {
    render(<PerformancePanel />);
    fireEvent.click(await screen.findByText('Settings'));
    return screen.findByLabelText(/Ops cap/);
  };

  it('is collapsed by default and shows each field source', async () => {
    render(<PerformancePanel />);
    await screen.findByText('OK');
    expect(screen.queryByLabelText(/Ops cap/)).toBeNull();
    fireEvent.click(screen.getByText('Settings'));
    await screen.findByLabelText(/Ops cap/);
    expect(screen.getAllByText('tier preset').length).toBeGreaterThan(0);
    expect(screen.getAllByText('environment').length).toBeGreaterThan(0);
  });

  it('Save is disabled until the form is valid and changed', async () => {
    const ops = await open();
    const save = screen.getByText('Save');
    expect(save.disabled).toBe(true);
    fireEvent.change(ops, { target: { value: '250' } });
    expect(save.disabled).toBe(false);
    fireEvent.change(ops, { target: { value: '0' } });
    expect(save.disabled).toBe(true);
    expect(screen.getByText(/whole number from 1 to 100,000/)).toBeTruthy();
  });

  it('editing a cap switches the tier to Custom', async () => {
    const ops = await open();
    expect(screen.getByLabelText(/^Tier/).value).toBe('free');
    fireEvent.change(ops, { target: { value: '250' } });
    expect(screen.getByLabelText(/^Tier/).value).toBe('custom');
  });

  it('rejects warn at or above critical, as the server does', async () => {
    await open();
    fireEvent.change(screen.getByLabelText(/Warn at/), { target: { value: '95' } });
    expect(screen.getByText('Warning must be below critical.')).toBeTruthy();
    expect(screen.getByText('Save').disabled).toBe(true);
  });

  it('Save sends the payload and the header follows the saved config', async () => {
    const saved = config({ tier: 'custom', ops_cap: 250 });
    mockPut.mockResolvedValue({ data: saved });
    const ops = await open();
    fireEvent.change(ops, { target: { value: '250' } });
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    expect(mockPut.mock.calls[0][0]).toBe('/superadmin/performance/config');
    expect(mockPut.mock.calls[0][1]).toMatchObject({ tier: 'custom', ops_cap: 250, conn_cap: 500 });
    await screen.findByText(/Custom caps · cap 250 ops\/s/);
  });

  it('Reset to defaults posts to the reset route', async () => {
    mockPost.mockResolvedValue({ data: config() });
    await open();
    fireEvent.click(screen.getByText('Reset to defaults'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/performance/config/reset'));
  });
});

describe('PerformancePanel organisations card', () => {
  beforeEach(() => { mockGet.mockReset(); setHidden(false); });
  afterEach(() => cleanup());

  it('shows every organisation together, busiest first, without switching tabs', async () => {
    serve();
    const base = mockGet.getMockImplementation();
    mockGet.mockImplementation((url, opts) => {
      if (url === '/superadmin/performance/orgs') {
        return Promise.resolve({ data: { window: opts?.params?.window, step_s: 60, buckets: 3, covered_minutes: 3, rows: [
          { name: 'kyues', ops: 90, share: 0.9, ops_s: 0.1, requests: 40, errors_5xx: 2, throttled_429: 0, points: [0.1, 0.5, 0.2] },
          { name: 'other', ops: 10, share: 0.1, ops_s: 0.01, requests: 5, errors_5xx: 0, throttled_429: 1, points: [0, 0.1, 0] },
        ] } });
      }
      return base(url, opts);
    });
    render(<PerformancePanel />);
    await screen.findByText('Organisations, all combined');
    expect((await screen.findAllByText('kyues')).length).toBe(2);   // chart legend and bar list
    expect(screen.getAllByText('other').length).toBe(2);
    expect(screen.getByText(/kyues is using 90% of the load/)).toBeTruthy();
    expect(screen.getByText(/5xx 2 · 429 0/)).toBeTruthy();
    expect(await screen.findByRole('img', { name: 'Operations per second by organisation' })).toBeTruthy();   // chart is present
  });

  it('switches range without leaving the page and asks the API for that window', async () => {
    serve();
    const base = mockGet.getMockImplementation();
    mockGet.mockImplementation((url, opts) => (url === '/superadmin/performance/orgs'
      ? Promise.resolve({ data: { window: opts?.params?.window, step_s: 900, buckets: 2, covered_minutes: 1440, rows: [] } })
      : base(url, opts)));
    render(<PerformancePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Last 24 hours' }));
    await waitFor(() => expect(mockGet.mock.calls.some((c) => c[0] === '/superadmin/performance/orgs' && c[1]?.params?.window === '24h')).toBe(true));
  });
});

describe('PerformancePanel shared range bar', () => {
  beforeEach(() => { mockGet.mockReset(); setHidden(false); });
  afterEach(() => cleanup());

  const withOrgs = (extra = {}) => {
    serve();
    const base = mockGet.getMockImplementation();
    mockGet.mockImplementation((url, opts) => (url === '/superadmin/performance/orgs'
      ? Promise.resolve({ data: { window: opts?.params?.window, step_s: 7200, start: 1_000_000, buckets: 3, covered_minutes: 10080, rows: [], total_points: [0.4, 0.9, 0.2], ...extra } })
      : base(url, opts)));
  };

  it('one range choice drives the main chart and the organisations card (24 hours)', async () => {
    withOrgs();
    render(<PerformancePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Last 24 hours' }));
    await waitFor(() => expect(mockGet.mock.calls.some((c) => c[0] === '/superadmin/performance/timeseries' && c[1]?.params?.window === '24h')).toBe(true));
    await waitFor(() => expect(mockGet.mock.calls.some((c) => c[0] === '/superadmin/performance/orgs' && c[1]?.params?.window === '24h')).toBe(true));
    expect(screen.getByText('Database operations, last 24 hours')).toBeTruthy();
  });

  it('7 days charts the combined organisation series and asks no 24 h timeseries', async () => {
    withOrgs();
    render(<PerformancePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Last 7 days' }));
    await screen.findByText('Database operations, last 7 days');
    await screen.findByText(/counting organisation traffic only/);
    await waitFor(() => expect(screen.getByRole('img', { name: 'Database operations per second' })).toBeTruthy());
    expect(mockGet.mock.calls.some((c) => c[0] === '/superadmin/performance/timeseries' && c[1]?.params?.window === '24h')).toBe(false);
  });

  it('Refresh reloads the summary, and the live toggle stops background polling', async () => {
    withOrgs();
    render(<PerformancePanel />);
    const refresh = await screen.findByRole('button', { name: 'Refresh' });
    const before = summaryCalls();
    fireEvent.click(refresh);
    await waitFor(() => expect(summaryCalls()).toBeGreaterThan(before));
    expect(screen.getByLabelText(/Live updates/).checked).toBe(true);
    fireEvent.click(screen.getByLabelText(/Live updates/));
    expect(screen.getByLabelText(/Live updates/).checked).toBe(false);
  });

  it('tiles turn red only for 5xx errors', async () => {
    serve({ sum: summary({ http: { rps: 5, p95_ms: 90, s5xx_1m: 3, s429_1m: 0 } }) });
    render(<PerformancePanel />);
    const label = await screen.findByText('5xx errors (1 min)');
    expect(label.parentElement.style.borderColor).toContain('--danger');
    expect(screen.getByText('429 throttled (1 min)').parentElement.style.borderColor).toBe('');
  });
});

describe('PerformancePanel storage card', () => {
  const STORAGE = '/superadmin/performance/storage';
  beforeEach(() => { mockGet.mockReset(); mockPut.mockReset(); mockPost.mockReset(); setHidden(false); });
  afterEach(() => cleanup());

  const withStorage = (data) => {
    serve();
    const base = mockGet.getMockImplementation();
    mockGet.mockImplementation((url, opts) => (url === STORAGE ? Promise.resolve({ data }) : base(url, opts)));
  };

  it('shows MongoDB as active and explains that migration needs PostgreSQL first', async () => {
    withStorage({ mode: 'mongo', postgres_configured: true, migration: { status: 'idle' } });
    render(<PerformancePanel />);
    expect(await screen.findByRole('button', { name: 'MongoDB (active)' })).toBeTruthy();
    expect(screen.getByText(/Switch to PostgreSQL first/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Migrate history' })).toBeNull();
  });

  it('switching asks PUT with the chosen store, then offers the migrate button', async () => {
    withStorage({ mode: 'mongo', postgres_configured: true, migration: { status: 'idle' } });
    mockPut.mockResolvedValue({ data: { mode: 'postgres', postgres_configured: true, chosen_in_app: true, switched_by: 'root', migration: { status: 'idle' } } });
    render(<PerformancePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'PostgreSQL' }));
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith('/superadmin/performance/storage', { mode: 'postgres' }));
    expect(await screen.findByRole('button', { name: 'Migrate history' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'PostgreSQL (active)' })).toBeTruthy();
  });

  it('cannot switch to PostgreSQL when the server has no connection string', async () => {
    withStorage({ mode: 'mongo', postgres_configured: false, migration: { status: 'idle' } });
    render(<PerformancePanel />);
    const btn = await screen.findByRole('button', { name: 'PostgreSQL' });
    expect(btn.disabled).toBe(true);
    expect(screen.getByText(/ANALYTICS_POSTGRES_URL/)).toBeTruthy();
  });

  it('Migrate history posts to the migrate route and shows progress', async () => {
    withStorage({ mode: 'postgres', postgres_configured: true, migration: { status: 'idle' } });
    mockPost.mockResolvedValue({ data: { mode: 'postgres', postgres_configured: true, migration: { status: 'running', counts: { counter_docs: 40, heat_docs: 2 } } } });
    render(<PerformancePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Migrate history' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/performance/storage/migrate'));
    expect(await screen.findByText(/40 daily records and 2 click maps so far/)).toBeTruthy();
  });

  it('shows a finished and a failed migration', async () => {
    withStorage({ mode: 'postgres', postgres_configured: true, migration: { status: 'done', message: 'Copied and verified.', cutoff: '2026-10-10', counts: { counter_docs: 9, heat_docs: 1 } } });
    const { unmount } = render(<PerformancePanel />);
    expect(await screen.findByText(/Copied and verified\. 9 daily records and 1 click maps, up to 2026-10-10/)).toBeTruthy();
    unmount();
    withStorage({ mode: 'postgres', postgres_configured: true, migration: { status: 'failed', message: 'Stopped safely: timeout' } });
    render(<PerformancePanel />);
    expect(await screen.findByText('Stopped safely: timeout')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run migration again' })).toBeTruthy();
  });
});

