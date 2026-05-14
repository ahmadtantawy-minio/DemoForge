import { create } from "zustand";
import type { DemoSummary, ContainerInstance } from "../types";

type ViewType = "diagram" | "control-plane";
export type PageKey = "home" | "designer" | "templates" | "images" | "readiness" | "fa-management" | "connectivity" | "settings";

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
  clusterHealth: Record<string, string>;
  activeView: ViewType;
  currentPage: PageKey;
  cockpitEnabled: boolean;
  walkthroughOpen: boolean;
  /** Hide left/right/bottom chrome to maximize canvas or control plane. */
  layoutFocusMode: boolean;
  toggleLayoutFocus: () => void;
  setLayoutFocusMode: (on: boolean) => void;
  /** Red laser-pointer dot replaces the cursor for demo presentations. */
  laserPointerMode: boolean;
  toggleLaserPointer: () => void;
  showFaNotes: boolean;
  setShowFaNotes: (v: boolean) => void;
  resilienceProbes: ResilienceProbe[];
  faId: string;
  faIdentified: boolean;
  faMode: string;
  /** True when running dev-start (local hub-api), false when dev-start-gcp, null in non-dev modes */
  hubLocal: boolean | null;
  setFaIdentity: (id: string, identified: boolean, mode?: string, hubLocal?: boolean | null) => void;
  setDemos: (demos: DemoSummary[]) => void;
  setActiveDemoId: (id: string | null) => void;
  setInstances: (instances: ContainerInstance[]) => void;
  setClusterHealth: (health: Record<string, string>) => void;
  setActiveView: (view: ViewType) => void;
  setCurrentPage: (page: PageKey) => void;
  toggleCockpit: () => void;
  toggleWalkthrough: () => void;
  setWalkthroughOpen: (open: boolean) => void;
  updateDemoStatus: (id: string, status: DemoSummary["status"]) => void;
  setResilienceProbes: (probes: ResilienceProbe[]) => void;
}

function viewFromPath(path: string): { demoId: string | null; view: ViewType; page: PageKey } {
  if (path === "/" || path === "") return { demoId: null, view: "diagram", page: "home" };
  if (path === "/templates") return { demoId: null, view: "diagram", page: "templates" };
  if (path === "/images") return { demoId: null, view: "diagram", page: "images" };
  if (path === "/readiness") return { demoId: null, view: "diagram", page: "readiness" };
  if (path === "/fa-management") return { demoId: null, view: "diagram", page: "fa-management" };
  if (path === "/connectivity") return { demoId: null, view: "diagram", page: "connectivity" };
  if (path === "/settings") return { demoId: null, view: "diagram", page: "settings" };
  const m = path.match(/^\/demo\/([^/]+)(\/instances)?/);
  if (m) return { demoId: m[1], view: m[2] ? "control-plane" : "diagram", page: "designer" };
  return { demoId: null, view: "diagram", page: "home" };
}

function pathFromState(demoId: string | null, view: ViewType, page: PageKey): string {
  if (page === "templates") return "/templates";
  if (page === "images") return "/images";
  if (page === "readiness") return "/readiness";
  if (page === "fa-management") return "/fa-management";
  if (page === "connectivity") return "/connectivity";
  if (page === "settings") return "/settings";
  if (page === "home" || !demoId) return "/";
  if (view === "control-plane") return `/demo/${demoId}/instances`;
  return `/demo/${demoId}`;
}

function pushUrl(demoId: string | null, view: ViewType, page: PageKey) {
  const target = pathFromState(demoId, view, page);
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
  clusterHealth: {},
  activeView: initial.view,
  currentPage: initial.page,
  cockpitEnabled: false,
  walkthroughOpen: false,
  layoutFocusMode: false,
  toggleLayoutFocus: () => set({ layoutFocusMode: !get().layoutFocusMode }),
  setLayoutFocusMode: (on) => set({ layoutFocusMode: on }),
  laserPointerMode: false,
  toggleLaserPointer: () => set({ laserPointerMode: !get().laserPointerMode }),
  showFaNotes: false,
  setShowFaNotes: (v) => set({ showFaNotes: v }),
  resilienceProbes: [],
  faId: "",
  faIdentified: false,
  faMode: "standard",
  hubLocal: null,
  setFaIdentity: (id, identified, mode, hubLocal) => set({ faId: id, faIdentified: identified, faMode: mode || "standard", hubLocal: hubLocal ?? null }),

  setDemos: (demos) => set({ demos }),

  setActiveDemoId: (id) => {
    const page = id ? "designer" : get().currentPage;
    set({ activeDemoId: id, currentPage: page });
    pushUrl(id, get().activeView, page);
  },

  setInstances: (instances) => set({ instances }),

  setClusterHealth: (health) => set({ clusterHealth: health }),

  setActiveView: (view) => {
    set({ activeView: view });
    pushUrl(get().activeDemoId, view, get().currentPage);
  },

  setCurrentPage: (page) => {
    set({ currentPage: page });
    pushUrl(get().activeDemoId, get().activeView, page);
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
  const { demoId, view, page } = viewFromPath(window.location.pathname);
  useDemoStore.setState({ activeDemoId: demoId, activeView: view, currentPage: page, layoutFocusMode: false });
});
