import { describe, it, expect, beforeEach } from 'vitest';
import { AxiosError } from 'axios';
import api, { retryConfig, DEFAULT_TIMEOUT_MS, shouldReportNetFail, _resetNetFailForTests } from './api';

// Fake transport: replays a scripted list of outcomes and records every attempt.
function script(outcomes) {
  const calls = [];
  api.defaults.adapter = async (config) => {
    calls.push({ method: config.method, url: config.url, timeout: config.timeout });
    const o = outcomes[Math.min(calls.length - 1, outcomes.length - 1)];
    if (o === 'network') throw new AxiosError('Network Error', 'ERR_NETWORK', config);
    if (o === 'timeout') throw new AxiosError('timeout', 'ECONNABORTED', config);
    const res = { data: o.data ?? {}, status: o.status, statusText: '', headers: {}, config };
    if (o.status >= 400) throw new AxiosError('bad', 'ERR_BAD_RESPONSE', config, null, res);
    return res;
  };
  return calls;
}

describe('shared api instance', () => {
  beforeEach(() => { retryConfig.baseMs = 1; sessionStorage.clear(); });

  it('has a default timeout', () => {
    expect(api.defaults.timeout).toBe(DEFAULT_TIMEOUT_MS);
  });

  it('retries a GET after a network error and then succeeds', async () => {
    const calls = script(['network', 'network', { status: 200, data: { ok: 1 } }]);
    const r = await api.get('/positions');
    expect(r.data).toEqual({ ok: 1 });
    expect(calls).toHaveLength(3);
  });

  it('retries a GET on 503 and on timeout, but gives up after the max', async () => {
    const calls = script([{ status: 503 }]);
    await expect(api.get('/positions')).rejects.toMatchObject({ response: { status: 503 } });
    expect(calls).toHaveLength(1 + retryConfig.max);
    const c2 = script(['timeout']);
    await expect(api.get('/positions')).rejects.toMatchObject({ code: 'ECONNABORTED' });
    expect(c2).toHaveLength(1 + retryConfig.max);
  });

  it('does not retry real answers (4xx, 500)', async () => {
    for (const status of [400, 401, 403, 404, 409, 500]) {
      const calls = script([{ status }]);
      await expect(api.get('/positions')).rejects.toMatchObject({ response: { status } });
      expect(calls).toHaveLength(1);
    }
  });

  it('NEVER retries a write, including votes', async () => {
    for (const url of ['/vote', '/vote-bulk', '/admin/voters/export']) {
      const calls = script(['network']);
      await expect(api.post(url, {})).rejects.toBeTruthy();
      expect(calls).toHaveLength(1);
    }
  });

  it('honours the per-call opt-out', async () => {
    const calls = script(['network']);
    await expect(api.get('/health', { __noRetry: true })).rejects.toBeTruthy();
    expect(calls).toHaveLength(1);
  });

  it('gives votes and uploads a longer timeout than the default', async () => {
    const calls = script([{ status: 200 }]);
    await api.post('/vote', {});
    await api.post('/upload', new FormData());
    await api.get('/positions');
    expect(calls[0].timeout).toBeGreaterThan(DEFAULT_TIMEOUT_MS);
    expect(calls[1].timeout).toBeGreaterThan(DEFAULT_TIMEOUT_MS);
    expect(calls[2].timeout).toBe(DEFAULT_TIMEOUT_MS);
  });
});

describe('analytics hygiene (guide 5.1 / 5.2)', () => {
  beforeEach(() => { retryConfig.baseMs = 1; sessionStorage.clear(); _resetNetFailForTests(); });

  const capture = (type) => {
    const seen = [];
    const fn = (e) => seen.push(e.detail);
    window.addEventListener(type, fn);
    return { seen, off: () => window.removeEventListener(type, fn) };
  };

  it('never reports /health network failures (the boot wake-up loop retries it by design)', async () => {
    script(['network']);
    const nf = capture('an:netfail');
    await expect(api.get('/health', { __noRetry: true })).rejects.toBeTruthy();
    nf.off();
    expect(nf.seen).toHaveLength(0);
  });

  it('reports a failing route once per 30 s, not once per retry', async () => {
    script(['network']);
    const nf = capture('an:netfail');
    await expect(api.get('/positions')).rejects.toBeTruthy();    // 3 attempts (1 + 2 retries)
    nf.off();
    expect(nf.seen).toHaveLength(1);
  });

  it('tells analytics which route succeeded, without the query string', async () => {
    script([{ status: 200 }]);
    const ev = capture('an:api');
    await api.get('/election-status?x=1');
    ev.off();
    expect(ev.seen[0]).toMatchObject({ ok: true, url: '/election-status' });
  });

  it('shouldReportNetFail enforces the 30 s gap per route', () => {
    expect(shouldReportNetFail('/a', 1000)).toBe(true);
    expect(shouldReportNetFail('/a', 20000)).toBe(false);
    expect(shouldReportNetFail('/b', 20000)).toBe(true);
    expect(shouldReportNetFail('/a', 31001)).toBe(true);
  });
});
