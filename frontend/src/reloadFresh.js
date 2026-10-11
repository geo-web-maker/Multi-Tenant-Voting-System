async function reloadFresh() {
  try {
    if ('caches' in window) await Promise.all((await caches.keys()).map(k => caches.delete(k)))
    if ('serviceWorker' in navigator) await Promise.all((await navigator.serviceWorker.getRegistrations()).map(r => r.unregister()))
  } catch { /* best effort: still reload */ }
  window.location.reload()
}

export default reloadFresh
