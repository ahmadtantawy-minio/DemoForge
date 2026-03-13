import { useEffect, useState } from "react";
import { useDemoStore } from "./stores/demoStore";
import { fetchDemos } from "./api/client";
import Toolbar from "./components/toolbar/Toolbar";
import ComponentPalette from "./components/palette/ComponentPalette";
import DiagramCanvas from "./components/canvas/DiagramCanvas";
import PropertiesPanel from "./components/properties/PropertiesPanel";
import ControlPlane from "./components/control-plane/ControlPlane";
import TerminalPanel from "./components/terminal/TerminalPanel";

export default function App() {
  const { setDemos, activeView } = useDemoStore();
  const [terminalTabs, setTerminalTabs] = useState<{ nodeId: string }[]>([]);

  useEffect(() => {
    fetchDemos()
      .then((res) => setDemos(res.demos))
      .catch(() => {});
  }, [setDemos]);

  const openTerminal = (nodeId: string) => {
    setTerminalTabs((prev) =>
      prev.find((t) => t.nodeId === nodeId) ? prev : [...prev, { nodeId }]
    );
  };

  return (
    <div className="flex flex-col h-screen bg-gray-100 overflow-hidden">
      {/* Top bar */}
      <Toolbar />

      {/* Main area */}
      <div className="flex flex-1 min-h-0">
        {/* Left sidebar - Component Palette */}
        <div className="w-48 flex-shrink-0 h-full">
          <ComponentPalette />
        </div>

        {/* Center - Diagram or Control Plane */}
        <div className="flex-1 min-w-0 h-full">
          {activeView === "diagram" ? (
            <DiagramCanvas />
          ) : (
            <ControlPlane onOpenTerminal={openTerminal} />
          )}
        </div>

        {/* Right sidebar - Properties Panel */}
        <div className="w-72 flex-shrink-0 h-full">
          <PropertiesPanel />
        </div>
      </div>

      {/* Bottom - Terminal Panel */}
      <div className="h-64 flex-shrink-0 border-t border-gray-300">
        <TerminalPanel extraTabs={terminalTabs} />
      </div>
    </div>
  );
}
