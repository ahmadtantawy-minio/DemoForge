/**
 * Persist integration_events for the LogViewer Integrations tab across refreshes while a demo run is active.
 * Keys: demoId + run fingerprint (container names). Retains at least the last 10 minutes by ts_ms.
 */

export type IntegrationEventRow = {
  id?: string;
  ts_ms?: number;
  node_id?: string;
  level?: string;
  kind?: string;
  message?: string;
  details?: string;
};

const STORAGE_VERSION = "v1";
const STORAGE_PREFIX = `demoforge:integrationEvents:${STORAGE_VERSION}`;
const SESSION_LAST_RUN_FP = "demoforge:integ:lastRunFp:";
/** Wall-clock window for events that have ts_ms */
export const INTEGRATION_EVENTS_RETENTION_MS = 10 * 60 * 1000;
const MAX_EVENTS = 5000;

function fnv1a32(s: string): string {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16);
}

/**
 * Identifies a "run" for a demo: stable across page refresh while the same containers are up;
 * changes when the stack is recreated (redeploy). When instances are empty, reuse last fingerprint from sessionStorage.
 */
export function resolveIntegrationRunFingerprint(
  demoId: string,
  instances: { container_name: string }[],
): string {
  const names = instances
    .map((i) => i.container_name)
    .sort()
    .join("\u001e");
  if (names.length > 0) {
    const fp = fnv1a32(`${demoId}\u001e${names}`);
    try {
      sessionStorage.setItem(SESSION_LAST_RUN_FP + demoId, fp);
    } catch {
      /* ignore */
    }
    return fp;
  }
  try {
    const last = sessionStorage.getItem(SESSION_LAST_RUN_FP + demoId);
    if (last) return last;
  } catch {
    /* ignore */
  }
  return `${demoId}:nostack`;
}

function storageKey(demoId: string, runFingerprint: string): string {
  return `${STORAGE_PREFIX}:${demoId}:${runFingerprint}`;
}

function eventKey(e: IntegrationEventRow): string {
  if (e.id && String(e.id).length > 0) return `id:${e.id}`;
  return `k:${e.ts_ms ?? 0}:${e.kind ?? ""}:${e.message ?? ""}:${e.node_id ?? ""}`;
}

export function loadStoredIntegrationEvents(demoId: string, runFingerprint: string): IntegrationEventRow[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(storageKey(demoId, runFingerprint));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x) => x && typeof x === "object") as IntegrationEventRow[];
  } catch {
    return [];
  }
}

function pruneByRetention(events: IntegrationEventRow[], now: number): IntegrationEventRow[] {
  const cutoff = now - INTEGRATION_EVENTS_RETENTION_MS;
  const withTs = events.filter((e) => typeof e.ts_ms === "number");
  const withoutTs = events.filter((e) => typeof e.ts_ms !== "number");
  const keptTs = withTs.filter((e) => (e.ts_ms as number) >= cutoff);
  const merged = [...keptTs, ...withoutTs];
  merged.sort((a, b) => {
    const ta = typeof a.ts_ms === "number" ? a.ts_ms : 0;
    const tb = typeof b.ts_ms === "number" ? b.ts_ms : 0;
    if (ta !== tb) return ta - tb;
    return eventKey(a).localeCompare(eventKey(b));
  });
  if (merged.length <= MAX_EVENTS) return merged;
  return merged.slice(-MAX_EVENTS);
}

/**
 * Merge API snapshot with previously stored events, dedupe by id/composite key, prune to retention window.
 */
export function mergePersistedIntegrationEvents(
  demoId: string,
  runFingerprint: string,
  fromApi: IntegrationEventRow[],
): IntegrationEventRow[] {
  const now = Date.now();
  const stored = loadStoredIntegrationEvents(demoId, runFingerprint);
  const map = new Map<string, IntegrationEventRow>();

  for (const e of stored) {
    map.set(eventKey(e), e);
  }
  for (const e of fromApi) {
    map.set(eventKey(e), e);
  }

  const merged = pruneByRetention([...map.values()], now);

  try {
    localStorage.setItem(storageKey(demoId, runFingerprint), JSON.stringify(merged));
  } catch {
    /* quota / private mode */
  }

  return merged;
}
