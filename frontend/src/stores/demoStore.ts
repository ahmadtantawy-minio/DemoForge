import { create } from "zustand";
import type { DemoSummary, ContainerInstance } from "../types";

interface DemoState {
  demos: DemoSummary[];
  activeDemoId: string | null;
  instances: ContainerInstance[];
  activeView: "diagram" | "control-plane" | "demos";
  setDemos: (demos: DemoSummary[]) => void;
  setActiveDemoId: (id: string | null) => void;
  setInstances: (instances: ContainerInstance[]) => void;
  setActiveView: (view: "diagram" | "control-plane" | "demos") => void;
  updateDemoStatus: (id: string, status: DemoSummary["status"]) => void;
}

export const useDemoStore = create<DemoState>((set, get) => ({
  demos: [],
  activeDemoId: null,
  instances: [],
  activeView: "diagram",

  setDemos: (demos) => set({ demos }),
  setActiveDemoId: (id) => set({ activeDemoId: id }),
  setInstances: (instances) => set({ instances }),
  setActiveView: (view) => set({ activeView: view }),

  updateDemoStatus: (id, status) =>
    set({
      demos: get().demos.map((d) => (d.id === id ? { ...d, status } : d)),
    }),
}));
