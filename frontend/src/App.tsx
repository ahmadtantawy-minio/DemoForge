import { useCallback, useEffect, useRef, useState } from "react";
import { useDemoStore } from "./stores/demoStore";
import { useDebugStore } from "./stores/debugStore";
import { fetchDemos, fetchInstances } from "./api/client";
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

export default function App() {
  const { setDemos, setInstances, activeDemoId, demos, activeView } = useDemoStore();
  const debugOpen = useDebugStore((s) => s.isOpen);
  const [terminalTabs, setTerminalTabs] = useState<{ nodeId: string }[]>([]);
  const [terminalHeight, setTerminalHeight] = useState(350);
  const isDragging = useRef(false);

  // Initial load + periodic sync of demo status from backend
  useEffect(() => {
    const sync = () => fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
    sync();
    const interval = setInterval(sync, 5000);
    return () => clearInterval(interval);
  }, [setDemos]);

  // Poll instances when active demo is running
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  useEffect(() => {
    if (!activeDemoId || activeDemo?.status !== "running") {
      setInstances([]);
      return;
    }
    const syncInstances = () =>
      fetchInstances(activeDemoId).then((res) => setInstances(res.instances)).catch(() => {});
    syncInstances();
    const interval = setInterval(syncInstances, 5000);
    return () => clearInterval(interval);
  }, [activeDemoId, activeDemo?.status, setInstances]);

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
            <DiagramCanvas onOpenTerminal={openTerminal} />
          ) : (
            <ControlPlane onOpenTerminal={openTerminal} />
          )}
        </div>

        {/* Right sidebar - Properties Panel (only in diagram view with active demo) */}
        {showSidebars && (
          <div className="w-72 flex-shrink-0 h-full">
            <PropertiesPanel />
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
