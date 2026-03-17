import { create } from "zustand";
import type { DemoSummary, ContainerInstance } from "../types";

type ViewType = "diagram" | "control-plane";

export interface ResilienceProbe {
  node_id: string;
  last_line: string;
  status: "ok" | "fail" | "unknown";
  seq: number | null;
  write_ms: number | null;
  read_ms: number | null;
  objects: number | null;
  upstream: string;
}

interface DemoState {
  demos: DemoSummary[];
  activeDemoId: string | null;
  instances: ContainerInstance[];
  activeView: ViewType;
  cockpitEnabled: boolean;
  walkthroughOpen: boolean;
  resilienceProbes: ResilienceProbe[];
  setDemos: (demos: DemoSummary[]) => void;
  setActiveDemoId: (id: string | null) => void;
  setInstances: (instances: ContainerInstance[]) => void;
  setActiveView: (view: ViewType) => void;
  toggleCockpit: () => void;
  toggleWalkthrough: () => void;
  setWalkthroughOpen: (open: boolean) => void;
  updateDemoStatus: (id: string, status: DemoSummary["status"]) => void;
  setResilienceProbes: (probes: ResilienceProbe[]) => void;
}

function viewFromPath(path: string): { demoId: string | null; view: ViewType } {
  const m = path.match(/^\/demo\/([^/]+)(\/instances)?/);
  if (m) {
    return { demoId: m[1], view: m[2] ? "control-plane" : "diagram" };
  }
  return { demoId: null, view: "diagram" };
}

function pathFromState(demoId: string | null, view: ViewType): string {
  if (!demoId) return "/";
  if (view === "control-plane") return `/demo/${demoId}/instances`;
  return `/demo/${demoId}`;
}

function pushUrl(demoId: string | null, view: ViewType) {
  const target = pathFromState(demoId, view);
  if (window.location.pathname !== target) {
    window.history.pushState(null, "", target);
  }
}

// Initialize from current URL
const initial = viewFromPath(window.location.pathname);

export const useDemoStore = create<DemoState>((set, get) => ({
  demos: [],
  activeDemoId: initial.demoId,
  instances: [],
  activeView: initial.view,
  cockpitEnabled: false,
  walkthroughOpen: false,
  resilienceProbes: [],

  setDemos: (demos) => set({ demos }),

  setActiveDemoId: (id) => {
    set({ activeDemoId: id });
    pushUrl(id, get().activeView);
  },

  setInstances: (instances) => set({ instances }),

  setActiveView: (view) => {
    set({ activeView: view });
    pushUrl(get().activeDemoId, view);
  },

  toggleCockpit: () => set({ cockpitEnabled: !get().cockpitEnabled }),

  toggleWalkthrough: () => set({ walkthroughOpen: !get().walkthroughOpen }),

  setWalkthroughOpen: (open) => set({ walkthroughOpen: open }),

  updateDemoStatus: (id, status) =>
    set({
      demos: get().demos.map((d) => (d.id === id ? { ...d, status } : d)),
    }),

  setResilienceProbes: (probes) => set({ resilienceProbes: probes }),
}));

// Handle browser back/forward
window.addEventListener("popstate", () => {
  const { demoId, view } = viewFromPath(window.location.pathname);
  useDemoStore.setState({ activeDemoId: demoId, activeView: view });
});
