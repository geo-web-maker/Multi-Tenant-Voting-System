// Storage access is a convenience, never a boot requirement. Private browsing, disabled
// storage, embedded browsers and quota failures must not leave the UI on a blank screen.
const memoryStores = {
  localStorage: new Map(),
  sessionStorage: new Map(),
};
const memoryOnlyStores = {
  localStorage: new Set(),
  sessionStorage: new Set(),
};

function makeSafeStorage(kind) {
  const memory = memoryStores[kind];
  const memoryOnly = memoryOnlyStores[kind];
  const nativeStore = () => {
    try { return typeof window !== 'undefined' ? window[kind] : null; }
    catch { return null; }
  };
  const nativeKeys = (store) => {
    const keys = [];
    for (let i = 0; i < store.length; i++) {
      try { const key = store.key(i); if (key != null) keys.push(key); } catch { break; }
    }
    return keys;
  };
  const combinedKeys = () => {
    const keys = [];
    try { const store = nativeStore(); if (store) keys.push(...nativeKeys(store)); } catch { /* use memory copy */ }
    for (const key of memory.keys()) if (!keys.includes(key)) keys.push(key);
    return keys;
  };
  const api = {
    getItem(key) {
      const k = String(key);
      try {
        const store = nativeStore();
        if (store) {
          const value = store.getItem(k);
          if (value != null) {
            memory.set(k, String(value));
            memoryOnly.delete(k);
            return String(value);
          }
          // If the browser's read succeeded but returned null after our write failed (quota,
          // policy), retain the in-memory copy. A successful wrapper remove/clear also clears it.
          if (memoryOnly.has(k)) return memory.has(k) ? memory.get(k) : null;
          memory.delete(k); // also respects raw Storage.clear() in existing app/tests
          return null;
        }
      } catch { /* fall back to this page's in-memory copy */ }
      return memory.has(k) ? memory.get(k) : null;
    },
    setItem(key, value) {
      const k = String(key); const v = String(value);
      memory.set(k, v);
      try {
        const store = nativeStore();
        if (!store) { memoryOnly.add(k); return; }
        store.setItem(k, v);
        memoryOnly.delete(k);
      } catch { memoryOnly.add(k); /* volatile fallback */ }
    },
    removeItem(key) {
      const k = String(key);
      memory.delete(k); memoryOnly.delete(k);
      try { nativeStore()?.removeItem(k); } catch { /* ignore disabled storage */ }
    },
    clear() {
      memory.clear(); memoryOnly.clear();
      try { nativeStore()?.clear(); } catch { /* ignore disabled storage */ }
    },
    key(index) {
      const i = Number(index);
      if (!Number.isInteger(i) || i < 0) return null;
      return combinedKeys()[i] ?? null;
    },
  };
  Object.defineProperty(api, 'length', {
    configurable: true,
    enumerable: false,
    get() { return combinedKeys().length; },
  });
  // Preserve Object.keys(storage) semantics for the few session cleanup helpers that enumerate keys.
  return new Proxy(api, {
    ownKeys() { return combinedKeys(); },
    getOwnPropertyDescriptor(_target, property) {
      if (typeof property !== 'string') return undefined;
      const exists = memory.has(property) || (() => {
        try { return nativeStore()?.getItem(property) != null; } catch { return false; }
      })();
      return exists ? { configurable: true, enumerable: true, writable: false, value: api.getItem(property) } : undefined;
    },
  });
}

export const safeSessionStorage = makeSafeStorage('sessionStorage');
export const safeLocalStorage = makeSafeStorage('localStorage');
