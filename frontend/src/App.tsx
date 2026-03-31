import { useCallback, useEffect, useRef, useState } from "react";
import { useDemoStore } from "./stores/demoStore";
import { useDiagramStore } from "./stores/diagramStore";
import { useDebugStore } from "./stores/debugStore";
import { fetchDemos, fetchInstances, getFailoverStatus, getResilienceStatus, fetchIdentity } from "./api/client";
import { Toaster } from "sonner";
import Toolbar from "./components/toolbar/Toolbar";
import ComponentPalette from "./components/palette/ComponentPalette";
import DiagramCanvas from "./components/canvas/DiagramCanvas";
import PropertiesPanel from "./components/properties/PropertiesPanel";
import ControlPlane from "./components/control-plane/ControlPlane";
import DemoManager from "./components/admin/DemoManager";
import TerminalPanel from "./components/terminal/TerminalPanel";
import DebugPanel from "./components/debug/DebugPanel";
import WelcomeScreen from "./components/shared/WelcomeScreen";
import CockpitOverlay from "./components/cockpit/CockpitOverlay";
import WalkthroughPanel from "./components/walkthrough/WalkthroughPanel";
import { getWalkthrough, WalkthroughStep } from "./api/client";
import AppNav from "./components/nav/AppNav";
import { HomePage } from "./pages/HomePage";
import { TemplatesPage } from "./pages/TemplatesPage";
import { ImagesPage } from "./pages/ImagesPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  const { setDemos, setInstances, activeDemoId, demos, activeView, cockpitEnabled, walkthroughOpen, setWalkthroughOpen, setResilienceProbes, currentPage } = useDemoStore();
  const debugOpen = useDebugStore((s) => s.isOpen);
  const [terminalTabs, setTerminalTabs] = useState<{ nodeId: string }[]>([]);
  const [walkthroughSteps, setWalkthroughSteps] = useState<WalkthroughStep[]>([]);
  const [terminalHeight, setTerminalHeight] = useState(200);
  const [leftPanelWidth, setLeftPanelWidth] = useState(192);
  const [rightPanelWidth, setRightPanelWidth] = useState(288);
  const isDragging = useRef(false);

  // Fetch FA identity on mount
  useEffect(() => {
    fetchIdentity()
      .then(({ fa_id, identified, mode }) => useDemoStore.getState().setFaIdentity(fa_id, identified, mode))
      .catch(() => {});
  }, []);

  // Initial load + periodic sync of demo status from backend
  useEffect(() => {
    const sync = () => fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
    sync();
    const interval = setInterval(sync, 5000);
    return () => clearInterval(interval);
  }, [setDemos]);

  // Poll instances when active demo is running or deploying
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  useEffect(() => {
    if (!activeDemoId || !["running", "deploying"].includes(activeDemo?.status || "")) {
      setInstances([]);
      return;
    }
    const syncInstances = () =>
      fetchInstances(activeDemoId).then((res) => {
        setInstances(res.instances);
        // Push health updates to diagram nodes
        const { updateNodeHealth } = useDiagramStore.getState();
        for (const inst of res.instances) {
          updateNodeHealth(inst.node_id, inst.health);
        }
        // Update edge config status on diagram edges
        if (res.edge_configs && res.edge_configs.length > 0) {
          const { edges, setEdges } = useDiagramStore.getState();
          // Build lookup: backend edge IDs may have "-cluster" suffix from compose_generator
          const edgeConfigMap = new Map<string, { status: string; error: string }>();
          for (const ec of res.edge_configs) {
            const entry = { status: ec.status, error: ec.error || "" };
            edgeConfigMap.set(ec.edge_id, entry);
            // Strip trailing "-cluster" suffix(es) so frontend edge IDs match
            let stripped = ec.edge_id;
            while (stripped.endsWith("-cluster")) {
              stripped = stripped.slice(0, -8);
              edgeConfigMap.set(stripped, entry);
            }
          }
          const updated = edges.map((e) => {
            const entry = edgeConfigMap.get(e.id);
            const configStatus = entry?.status || (e.data as any)?.configStatus;
            const configError = entry?.error || (e.data as any)?.configError || "";
            if (configStatus && (configStatus !== (e.data as any)?.configStatus || configError !== (e.data as any)?.configError)) {
              return { ...e, data: { ...e.data, configStatus, configError } };
            }
            return e;
          });
          if (updated.some((e, i) => e !== edges[i])) {
            setEdges(updated);
          }
        }
        // Update failover edge status
        getFailoverStatus(activeDemoId).then((fsRes) => {
          if (!fsRes.failover || fsRes.failover.length === 0) return;
          const { edges: currentEdges, setEdges: setCurrentEdges } = useDiagramStore.getState();
          let changed = false;
          const updatedEdges = currentEdges.map((e) => {
            const ed = e.data as any;
            if (ed?.connectionType !== "failover") return e;
            // Determine if this edge's target is the active upstream
            // Only match the failover entry whose gateway is this edge's source
            const sourceId = e.source;
            const targetId = e.target;
            const gwEntry = fsRes.failover.find((f) => f.gateway === sourceId);
            const isActive = !!(gwEntry && gwEntry.healthy && gwEntry.active_upstream && gwEntry.active_upstream.includes(targetId));
            if (ed.failoverActive !== isActive) {
              changed = true;
              return { ...e, data: { ...ed, failoverActive: isActive } };
            }
            return e;
          });
          if (changed) setCurrentEdges(updatedEdges);
        }).catch(() => {});
        // Poll resilience tester status
        getResilienceStatus(activeDemoId).then((rsRes) => {
          if (rsRes.probes && rsRes.probes.length > 0) {
            setResilienceProbes(rsRes.probes);
          }
        }).catch(() => {});
      }).catch(() => {});
    syncInstances();
    const interval = setInterval(syncInstances, 5000);
    return () => clearInterval(interval);
  }, [activeDemoId, activeDemo?.status, setInstances]);

  // Fetch walkthrough steps when panel opens
  useEffect(() => {
    if (!walkthroughOpen || !activeDemoId) return;
    getWalkthrough(activeDemoId)
      .then((res) => setWalkthroughSteps(res.walkthrough))
      .catch(() => setWalkthroughSteps([]));
  }, [walkthroughOpen, activeDemoId]);

  const openTerminal = (nodeId: string) => {
    setTerminalTabs((prev) =>
      prev.find((t) => t.nodeId === nodeId) ? prev : [...prev, { nodeId }]
    );
  };

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startY = e.clientY;
    const startH = terminalHeight;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newH = Math.max(150, Math.min(800, startH + (startY - ev.clientY)));
      setTerminalHeight(newH);
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [terminalHeight]);

  const onLeftResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startX = e.clientX;
    const startW = leftPanelWidth;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newW = Math.max(150, Math.min(400, startW + (ev.clientX - startX)));
      setLeftPanelWidth(newW);
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [leftPanelWidth]);

  const onRightResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startX = e.clientX;
    const startW = rightPanelWidth;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newW = Math.max(150, Math.min(400, startW + (startX - ev.clientX)));
      setRightPanelWidth(newW);
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [rightPanelWidth]);

  const isExperience = demos.find((d) => d.id === activeDemoId)?.mode === "experience";
  const showSidebars = activeDemoId && activeView === "diagram";
  const showLeftSidebar = showSidebars && !isExperience;
  const showRightSidebar = showSidebars && !isExperience;
  const showWelcome = !activeDemoId;

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <Toaster
        theme="dark"
        position="bottom-right"
        closeButton
        toastOptions={{
          style: { background: "#18181b", border: "1px solid #27272a", color: "#fafafa" },
          classNames: {
            error: "!border-red-800 !bg-red-950/90",
            actionButton: "!bg-zinc-700 !text-zinc-200 hover:!bg-zinc-600 !text-xs !px-2 !py-1",
          },
        }}
      />

      <AppNav />

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Home page */}
        <div style={{ display: currentPage === "home" ? "contents" : "none" }}>
          <HomePage />
        </div>

        {/* Designer - ALWAYS MOUNTED, hidden via display:none to preserve React Flow viewport state */}
        <div style={{ display: currentPage === "designer" ? "contents" : "none" }} className="flex flex-col h-full">
          {/* Top bar */}
          <Toolbar />

          {/* Main area */}
          <div className="flex flex-1 min-h-0">
            {/* Left sidebar - Component Palette (hidden in experience mode) */}
            {showLeftSidebar && (
              <div className="flex-shrink-0 h-full" style={{ width: leftPanelWidth }}>
                <ComponentPalette />
              </div>
            )}

            {/* Left resize handle */}
            {showLeftSidebar && (
              <div
                className="w-1 flex-shrink-0 bg-border hover:bg-primary/50 cursor-col-resize flex items-center justify-center"
                onMouseDown={onLeftResizeStart}
              >
                <div className="h-8 w-0.5 rounded-full bg-zinc-500" />
              </div>
            )}

            {/* Center content */}
            <div className="flex-1 min-w-0 h-full">
              {showWelcome ? (
                <WelcomeScreen />
              ) : activeView === "diagram" ? (
                <div className="relative w-full h-full">
                  <DiagramCanvas onOpenTerminal={openTerminal} />
                </div>
              ) : (
                <ControlPlane onOpenTerminal={openTerminal} />
              )}
            </div>

            {/* Right resize handle */}
            {showRightSidebar && (
              <div
                className="w-1 flex-shrink-0 bg-border hover:bg-primary/50 cursor-col-resize flex items-center justify-center"
                onMouseDown={onRightResizeStart}
              >
                <div className="h-8 w-0.5 rounded-full bg-zinc-500" />
              </div>
            )}

            {/* Right sidebar - Properties Panel (hidden in experience mode) */}
            {showRightSidebar && (
              <div className="flex-shrink-0 h-full" style={{ width: rightPanelWidth }}>
                {walkthroughOpen
                  ? <WalkthroughPanel steps={walkthroughSteps} onClose={() => setWalkthroughOpen(false)} />
                  : <PropertiesPanel />}
              </div>
            )}
          </div>

          {/* Floating Cockpit overlay */}
          {cockpitEnabled && activeDemoId && <CockpitOverlay />}

          {/* Bottom - Terminal or Debug Panel (resizable) - only when demo selected */}
          {activeDemoId && (
            <div className="flex-shrink-0" style={{ height: terminalHeight }}>
              <div
                className="h-2 bg-border hover:bg-primary/50 cursor-row-resize border-t border-border flex items-center justify-center"
                onMouseDown={onResizeStart}
              >
                <div className="w-8 h-0.5 rounded-full bg-zinc-500" />
              </div>
              <div className="h-[calc(100%-8px)]">
                {debugOpen ? <DebugPanel /> : <TerminalPanel extraTabs={terminalTabs} />}
              </div>
            </div>
          )}
        </div>

        {/* Templates page */}
        <div style={{ display: currentPage === "templates" ? "contents" : "none" }}>
          <TemplatesPage />
        </div>

        {/* Images page */}
        <div style={{ display: currentPage === "images" ? "contents" : "none" }}>
          <ImagesPage />
        </div>

        {/* Settings page */}
        <div style={{ display: currentPage === "settings" ? "contents" : "none" }}>
          <SettingsPage />
        </div>
      </main>
    </div>
  );
}
