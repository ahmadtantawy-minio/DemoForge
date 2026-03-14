import { create } from "zustand";

export interface DebugEntry {
  id: number;
  timestamp: string;
  level: "info" | "warn" | "error";
  source: string;
  message: string;
  details?: string;
}

let nextId = 1;

interface DebugState {
  entries: DebugEntry[];
  isOpen: boolean;
  addEntry: (level: DebugEntry["level"], source: string, message: string, details?: string) => void;
  clear: () => void;
  toggle: () => void;
  setOpen: (open: boolean) => void;
}

export const useDebugStore = create<DebugState>((set) => ({
  entries: [],
  isOpen: false,

  addEntry: (level, source, message, details) =>
    set((state) => ({
      entries: [
        ...state.entries,
        {
          id: nextId++,
          timestamp: new Date().toLocaleTimeString(),
          level,
          source,
          message,
          details,
        },
      ].slice(-200), // Keep last 200 entries
    })),

  clear: () => set({ entries: [] }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (open) => set({ isOpen: open }),
}));
