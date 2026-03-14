import { useState, useEffect, useRef } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { Button } from "@/components/ui/button";
import { X, Plus, TerminalSquare } from "lucide-react";
import TerminalTab from "./TerminalTab";

interface Tab {
  nodeId: string;
}

interface Props {
  extraTabs?: Tab[];
  onAddTab?: (nodeId: string) => void;
}

export default function TerminalPanel({ extraTabs = [], onAddTab }: Props) {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const closedTabsRef = useRef<Set<string>>(new Set());
  const { activeDemoId, instances } = useDemoStore();

  // Sync externally pushed tabs into local state (skip manually closed ones)
  useEffect(() => {
    setTabs((prev) => {
      const newTabs = extraTabs.filter(
        (et) => !prev.find((t) => t.nodeId === et.nodeId) && !closedTabsRef.current.has(et.nodeId)
      );
      if (newTabs.length === 0) return prev;
      return [...prev, ...newTabs];
    });
    if (extraTabs.length > 0) {
      const lastNew = extraTabs[extraTabs.length - 1];
      if (!closedTabsRef.current.has(lastNew.nodeId)) {
        setActiveTab((prev) => prev ?? lastNew.nodeId);
      }
    }
  }, [extraTabs]);

  const currentTab = activeTab ?? tabs[0]?.nodeId ?? null;

  const addTab = () => {
    if (!activeDemoId || instances.length === 0) return;
    const available = instances.filter((i) => i.has_terminal && !tabs.find((t) => t.nodeId === i.node_id));
    if (available.length === 0) return;
    const newTab = { nodeId: available[0].node_id };
    // Remove from closed set so it can be opened again
    closedTabsRef.current.delete(newTab.nodeId);
    setTabs((prev) => [...prev, newTab]);
    setActiveTab(newTab.nodeId);
    onAddTab?.(newTab.nodeId);
  };

  const closeTab = (nodeId: string) => {
    closedTabsRef.current.add(nodeId);
    setTabs((prev) => prev.filter((t) => t.nodeId !== nodeId));
    if (currentTab === nodeId) {
      const remaining = tabs.filter((t) => t.nodeId !== nodeId);
      setActiveTab(remaining.length > 0 ? remaining[0].nodeId : null);
    }
  };

  const handleAddTab = () => {
    if (!activeDemoId || instances.length === 0) return;
    addTab();
  };

  const hasTerminalContainers = instances.some((i) => i.has_terminal && !tabs.find((t) => t.nodeId === i.node_id));

  return (
    <div className="flex flex-col h-full bg-background border-t border-border">
      <div className="flex items-center bg-card border-b border-border overflow-x-auto">
        {tabs.map((tab) => (
          <div
            key={tab.nodeId}
            className={`flex items-center gap-1 px-3 py-1.5 text-xs cursor-pointer border-r border-border whitespace-nowrap transition-colors
              ${currentTab === tab.nodeId ? "bg-background text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setActiveTab(tab.nodeId)}
          >
            <TerminalSquare className="w-3 h-3" />
            <span>{tab.nodeId}</span>
            <button
              onClick={(e) => { e.stopPropagation(); closeTab(tab.nodeId); }}
              className="ml-1 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
          onClick={handleAddTab}
          disabled={!hasTerminalContainers}
          title={!hasTerminalContainers ? "No running containers available" : "Open terminal"}
        >
          <Plus className="w-3.5 h-3.5" />
        </Button>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        {currentTab && activeDemoId ? (
          <TerminalTab
            key={currentTab}
            demoId={activeDemoId}
            nodeId={currentTab}
            quickActions={instances.find((i) => i.node_id === currentTab)?.quick_actions ?? []}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
            <TerminalSquare className="w-6 h-6 text-muted-foreground/40" />
            <span className="text-xs">
              {instances.length === 0
                ? "No running containers available"
                : "No terminal open. Click + to open one."}
            </span>
          </div>
        )}
      </div>
      {/* Footer */}
      <div className="flex items-center justify-between px-3 py-1 bg-card border-t border-border text-xs text-muted-foreground flex-shrink-0">
        <span>{currentTab ? `Container: ${currentTab}` : "No terminal"}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-5 text-[10px] px-2 text-muted-foreground"
          disabled={!currentTab}
          onClick={() => { if (currentTab) closeTab(currentTab); }}
        >
          <X className="w-3 h-3 mr-1" />
          Clear
        </Button>
      </div>
    </div>
  );
}
