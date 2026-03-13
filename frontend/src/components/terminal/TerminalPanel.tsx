import { useState } from "react";
import { useDemoStore } from "../../stores/demoStore";
import TerminalTab from "./TerminalTab";

interface Tab {
  nodeId: string;
}

interface Props {
  extraTabs?: Tab[];
  onAddTab?: (nodeId: string) => void;
}

export default function TerminalPanel({ extraTabs = [], onAddTab }: Props) {
  const [tabs, setTabs] = useState<Tab[]>(extraTabs);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const { activeDemoId, instances } = useDemoStore();

  // Merge in any externally pushed tabs
  const allTabs = [...tabs, ...extraTabs.filter((et) => !tabs.find((t) => t.nodeId === et.nodeId))];
  const currentTab = activeTab ?? allTabs[0]?.nodeId ?? null;

  const addTab = () => {
    if (!activeDemoId || instances.length === 0) return;
    const available = instances.filter((i) => i.has_terminal && !allTabs.find((t) => t.nodeId === i.node_id));
    if (available.length === 0) return;
    const newTab = { nodeId: available[0].node_id };
    setTabs((prev) => [...prev, newTab]);
    setActiveTab(newTab.nodeId);
    onAddTab?.(newTab.nodeId);
  };

  const closeTab = (nodeId: string) => {
    setTabs((prev) => prev.filter((t) => t.nodeId !== nodeId));
    if (currentTab === nodeId) {
      setActiveTab(allTabs.find((t) => t.nodeId !== nodeId)?.nodeId ?? null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-gray-900 border-t border-gray-700">
      <div className="flex items-center bg-gray-800 border-b border-gray-700 overflow-x-auto">
        {allTabs.map((tab) => (
          <div
            key={tab.nodeId}
            className={`flex items-center gap-1 px-3 py-1.5 text-xs cursor-pointer border-r border-gray-700 whitespace-nowrap
              ${currentTab === tab.nodeId ? "bg-gray-900 text-white" : "text-gray-400 hover:text-gray-200"}`}
            onClick={() => setActiveTab(tab.nodeId)}
          >
            <span>{tab.nodeId}</span>
            <button
              onClick={(e) => { e.stopPropagation(); closeTab(tab.nodeId); }}
              className="ml-1 text-gray-500 hover:text-gray-200"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          onClick={addTab}
          className="px-3 py-1.5 text-gray-400 hover:text-white text-xs"
        >
          +
        </button>
      </div>
      <div className="flex-1 overflow-hidden">
        {currentTab && activeDemoId ? (
          <TerminalTab
            key={currentTab}
            demoId={activeDemoId}
            nodeId={currentTab}
            quickActions={instances.find((i) => i.node_id === currentTab)?.quick_actions ?? []}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-500 text-xs">
            No terminal open. Click + to open one.
          </div>
        )}
      </div>
    </div>
  );
}
