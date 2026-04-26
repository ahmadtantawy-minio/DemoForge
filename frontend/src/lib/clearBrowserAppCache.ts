/**
 * Clears DemoForge client-side persistence and optional browser caches, then reloads the tab.
 *
 * - localStorage: removes keys prefixed with `demoforge:` (integration logs, panel bounds).
 *   Does not remove `demoforge-theme`.
 * - sessionStorage: cleared entirely (proxy recovery prefix, integration run fingerprints).
 * - Cache Storage API: deletes all caches for this origin (if supported).
 * - Service workers: unregisters all for this origin (if supported).
 */
export async function clearBrowserCachesAndHardReload(): Promise<void> {
  if (typeof window === "undefined") return;

  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith("demoforge:")) {
        localStorage.removeItem(k);
      }
    }
  } catch {
    /* quota / private mode */
  }

  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }

  try {
    if (typeof caches !== "undefined" && typeof caches.keys === "function") {
      const names = await caches.keys();
      await Promise.all(names.map((name) => caches.delete(name)));
    }
  } catch {
    /* ignore */
  }

  try {
    if (navigator.serviceWorker?.getRegistrations) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch {
    /* ignore */
  }

  window.location.reload();
}
