import { describe, it, expect, afterEach, vi } from 'vitest';
import { resolveTemplate, setTemplateImpl, getTemplate } from './template';
import { renderHook, act } from '@testing-library/react';
import { setChrome, resetChrome, useChrome } from './templateChrome';
import { useBlueprint, useDefault, restoreTemplate } from './test/template';

afterEach(restoreTemplate);

describe('resolveTemplate (strict switch)', () => {
  it.each([
    ['blueprint', 'blueprint'],
    [undefined, 'default'],
    ['', 'default'],
    ['default', 'default'],
    ['Blueprint', 'default'],
    [' blueprint ', 'default'],
    ['bluprint', 'default'],
  ])('%j -> %s', (raw, want) => {
    expect(resolveTemplate(raw)).toBe(want);
  });
});

describe('registry', () => {
  it('setTemplateImpl(mod) sets html[data-template]; null removes it', () => {
    setTemplateImpl({ name: 'x' });
    expect(document.documentElement.dataset.template).toBe('blueprint');
    expect(getTemplate()).toEqual({ name: 'x' });
    setTemplateImpl(null);
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(getTemplate()).toBeNull();
  });
  it('helpers switch both ways', async () => {
    await useBlueprint();
    expect(document.documentElement.dataset.template).toBe('blueprint');
    expect(getTemplate().name).toBe('blueprint');
    useDefault();
    expect(document.documentElement.dataset.template).toBeUndefined();
  });
  it('blueprint index registers viewport-fit=cover only when loaded', async () => {
    const meta = document.createElement('meta');
    meta.name = 'viewport';
    meta.content = 'width=device-width, initial-scale=1.0';
    document.head.appendChild(meta);
    vi.resetModules();
    await import('./templates/blueprint/index.js');
    expect(meta.content).toMatch(/viewport-fit=cover/);
    vi.resetModules();
    await import('./templates/blueprint/index.js');
    expect(meta.content.match(/viewport-fit/g)).toHaveLength(1); // idempotent
    meta.remove();
  });
});

describe('chrome store', () => {
  it('notifies on real change only', () => {
    resetChrome();
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useChrome();
    });
    const base = renders;
    act(() => setChrome({ group: 'A' }));
    expect(result.current.group).toBe('A');
    const afterFirst = renders;
    expect(afterFirst).toBeGreaterThan(base);
    act(() => setChrome({ group: 'A' })); // equal patch: no re-render
    expect(renders).toBe(afterFirst);
    act(() => setChrome({ group: 'A', tab: 'T' })); // partial change
    expect(result.current.tab).toBe('T');
    act(() => resetChrome());
    expect(result.current.group).toBe('');
  });
});
