import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockGet = vi.fn();
vi.mock('./api', () => ({ default: { get: (...a) => mockGet(...a) } }));

import { fetchBootstrap, resetBootstrapCache } from './bootstrap';

const BOOT = { branding: { org_name: 'X' }, status: { is_open: true }, positions: [{ _id: '1' }] };

describe('E1: fetchBootstrap', () => {
  beforeEach(() => { mockGet.mockReset(); resetBootstrapCache(); });

  it('makes one request for concurrent callers and returns all three parts', async () => {
    mockGet.mockResolvedValue({ data: BOOT });
    const [a, b] = await Promise.all([fetchBootstrap(), fetchBootstrap()]);
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledWith('/public/bootstrap');
    expect(a).toEqual(BOOT); expect(b).toEqual(BOOT);
  });

  it('asks again when fresh data is requested', async () => {
    mockGet.mockResolvedValue({ data: BOOT });
    await fetchBootstrap(); await fetchBootstrap({ fresh: true });
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('falls back to the three original endpoints when bootstrap fails', async () => {
    mockGet.mockImplementation((url) => url === '/public/bootstrap'
      ? Promise.reject(new Error('404'))
      : Promise.resolve({ data: { '/superadmin/branding': BOOT.branding, '/election-status': BOOT.status, '/positions': BOOT.positions }[url] }));
    expect(await fetchBootstrap()).toEqual(BOOT);
    expect(mockGet.mock.calls.map(c => c[0]).sort()).toEqual(['/election-status', '/positions', '/public/bootstrap', '/superadmin/branding']);
  });

  it('a failed part falls back to null, never throws', async () => {
    mockGet.mockImplementation((url) => url === '/election-status'
      ? Promise.reject(new Error('x')) : url === '/public/bootstrap' ? Promise.reject(new Error('x'))
      : Promise.resolve({ data: url === '/positions' ? [] : {} }));
    const r = await fetchBootstrap();
    expect(r.status).toBeNull(); expect(r.positions).toEqual([]);
  });
});
