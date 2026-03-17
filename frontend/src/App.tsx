import { useCallback, useEffect, useRef, useState } from "react";
import { useDemoStore } from "./stores/demoStore";
import { useDiagramStore } from "./stores/diagramStore";
import { useDebugStore } from "./stores/debugStore";
import { fetchDemos, fetchInstances, getFailoverStatus } from "./api/client";
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

export default function App() {
  const { setDemos, setInstances, activeDemoId, demos, activeView, cockpitEnabled, walkthroughOpen, setWalkthroughOpen } = useDemoStore();
  const debugOpen = useDebugStore((s) => s.isOpen);
  const [terminalTabs, setTerminalTabs] = useState<{ nodeId: string }[]>([]);
  const [walkthroughSteps, setWalkthroughSteps] = useState<WalkthroughStep[]>([]);
  const [terminalHeight, setTerminalHeight] = useState(350);
  const isDragging = useRef(false);

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
          const edgeConfigMap = new Map<string, string>();
          for (const ec of res.edge_configs) {
            edgeConfigMap.set(ec.edge_id, ec.status);
            // Strip trailing "-cluster" suffix(es) so frontend edge IDs match
            let stripped = ec.edge_id;
            while (stripped.endsWith("-cluster")) {
              stripped = stripped.slice(0, -8);
              edgeConfigMap.set(stripped, ec.status);
            }
          }
          const updated = edges.map((e) => {
            const configStatus = edgeConfigMap.get(e.id) || (e.data as any)?.configStatus;
            if (configStatus && configStatus !== (e.data as any)?.configStatus) {
              return { ...e, data: { ...e.data, configStatus } };
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
            const targetId = e.target;
            const isActive = fsRes.failover.some((f) =>
              f.healthy && f.active_upstream && f.active_upstream.includes(targetId)
            );
            if (ed.failoverActive !== isActive) {
              changed = true;
              return { ...e, data: { ...ed, failoverActive: isActive } };
            }
            return e;
          });
          if (changed) setCurrentEdges(updatedEdges);
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

  const showSidebars = activeDemoId && activeView === "diagram";
  const showWelcome = !activeDemoId;

  return (
    <div className="flex flex-col h-screen bg-background text-foreground overflow-hidden">
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: { background: "#18181b", border: "1px solid #27272a", color: "#fafafa" },
        }}
      />

      {/* Top bar */}
      <Toolbar />

      {/* Main area */}
      <div className="flex flex-1 min-h-0">
        {/* Left sidebar - Component Palette (only in diagram view with active demo) */}
        {showSidebars && (
          <div className="w-48 flex-shrink-0 h-full">
            <ComponentPalette />
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

        {/* Right sidebar - Properties Panel or Cockpit (only in diagram view with active demo) */}
        {showSidebars && (
          <div className="w-72 flex-shrink-0 h-full">
            {walkthroughOpen
              ? <WalkthroughPanel steps={walkthroughSteps} onClose={() => setWalkthroughOpen(false)} />
              : cockpitEnabled ? <CockpitOverlay /> : <PropertiesPanel />}
          </div>
        )}
      </div>

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
  );
}
