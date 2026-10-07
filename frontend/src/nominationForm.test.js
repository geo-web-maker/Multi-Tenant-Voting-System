import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useNominationForm } from './nominationForm';
const get = vi.fn();
vi.mock('./api', () => ({ default: { get: (...a) => get(...a) } }));
describe('useNominationForm', () => {
  it('loads runtime settings and falls back disabled on errors', async () => { get.mockResolvedValue({ data: { enabled:true, required:false, title:'Signed Form' } }); const { result } = renderHook(() => useNominationForm(0)); await waitFor(() => expect(result.current.title).toBe('Signed Form')); expect(result.current.enabled).toBe(true); });
  it('hides config after a failed poll', async () => { get.mockRejectedValue(new Error('offline')); const { result } = renderHook(() => useNominationForm(0)); await waitFor(() => expect(result.current.enabled).toBe(false)); });
});
