import { create } from "zustand";

export interface DebugEntry {
  id: string;
  timestamp: string;
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

/** Main "Logs" tab — shared ring buffer (Lifecycle, Poll, etc. compete for space). */
const MAIN_LOG_CAP = 200;
/**
 * Dev Logs → Integrations tab only — Provision + Integration sources, kept separately so
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
      const entry: DebugEntry = {
        id: newEntryId(),
        timestamp: new Date().toLocaleTimeString(),
        level,
        source,
        message,
        details,
      };
      const pushMain = [...state.entries, entry].slice(-MAIN_LOG_CAP);
      const isIntegrationTab =
        source === "Integration" || source === "Provision";
      const pushInteg =
        isIntegrationTab
          ? [...state.integrationBuffer, entry].slice(-INTEGRATION_LOG_CAP)
          : state.integrationBuffer;
      return { entries: pushMain, integrationBuffer: pushInteg };
    }),

  clear: () => set({ entries: [] }),
  clearIntegrationBuffer: () => set({ integrationBuffer: [] }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (open) => set({ isOpen: open }),
}));
