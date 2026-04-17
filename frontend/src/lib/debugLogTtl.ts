/** Shared TTL for main Logs + Integrations buffers and integration-event dedup (see backlog). */
export const DEBUG_LOG_TTL_MS = 10 * 60 * 1000;

export function pruneByAge<T extends { createdAtMs?: number }>(
  items: T[],
  ttlMs: number,
  now: number = Date.now()
): T[] {
  const cutoff = now - ttlMs;
  return items.filter((e) => (e.createdAtMs ?? 0) >= cutoff);
}
