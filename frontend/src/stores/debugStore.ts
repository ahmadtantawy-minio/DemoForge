import { create } from "zustand";
import { DEBUG_LOG_TTL_MS, pruneByAge } from "../lib/debugLogTtl";

export interface DebugEntry {
  id: string;
  timestamp: string;
  /** Monotonic age for TTL eviction (default Date.now() at insert). */
  createdAtMs: number;
  level: "info" | "warn" | "error";
  source: string;
  message: string;
  details?: string;
}

function newEntryId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `d-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

/** Main Logs tab — shared ring buffer (Lifecycle, Poll, etc. compete for space). */
const MAIN_LOG_CAP = 200;
/**
 * Integrations tab only — Provision + Integration sources, kept separately so
 * lifecycle/poll noise does not evict integration lines.
 */
const INTEGRATION_LOG_CAP = 2500;

interface DebugState {
  entries: DebugEntry[];
  /** Integration + Provision only — shown on Integrations tab; not evicted by main log cap */
  integrationBuffer: DebugEntry[];
  isOpen: boolean;
  addEntry: (level: DebugEntry["level"], source: string, message: string, details?: string) => void;
  /** Clears main Logs tab only (Integrations buffer preserved). */
  clear: () => void;
  clearIntegrationBuffer: () => void;
  toggle: () => void;
  setOpen: (open: boolean) => void;
}

export const useDebugStore = create<DebugState>((set) => ({
  entries: [],
  integrationBuffer: [],
  isOpen: false,

  addEntry: (level, source, message, details) =>
    set((state) => {
      const now = Date.now();
      const entry: DebugEntry = {
        id: newEntryId(),
        timestamp: new Date().toLocaleTimeString(),
        createdAtMs: now,
        level,
        source,
        message,
        details,
      };
      const agedMain = pruneByAge(state.entries, DEBUG_LOG_TTL_MS);
      const agedInt = pruneByAge(state.integrationBuffer, DEBUG_LOG_TTL_MS);
      const pushMain = [...agedMain, entry].slice(-MAIN_LOG_CAP);
      const isIntegrationTab =
        source === "Integration" || source === "Provision";
      const pushInteg =
        isIntegrationTab
          ? [...agedInt, entry].slice(-INTEGRATION_LOG_CAP)
          : agedInt;
      return { entries: pushMain, integrationBuffer: pushInteg };
    }),

  clear: () => set({ entries: [] }),
  clearIntegrationBuffer: () => set({ integrationBuffer: [] }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (open) => set({ isOpen: open }),
}));

export { DEBUG_LOG_TTL_MS } from "../lib/debugLogTtl";
