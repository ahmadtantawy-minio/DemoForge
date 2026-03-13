import { useState } from "react";
import type { ContainerInstance } from "../../types";
import HealthBadge from "./HealthBadge";
import WebUIFrame from "./WebUIFrame";
import { useDiagramStore } from "../../stores/diagramStore";

interface Props {
  instance: ContainerInstance;
  demoId: string;
  onOpenTerminal: (nodeId: string) => void;
}

export default function ComponentCard({ instance, onOpenTerminal }: Props) {
  const [activeFrame, setActiveFrame] = useState<{ name: string; path: string } | null>(null);
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg shadow-sm p-3 mb-3 cursor-pointer hover:border-blue-300 transition-colors"
      onClick={() => setSelectedNode(instance.node_id)}
    >
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="font-semibold text-sm text-gray-800">{instance.node_id}</div>
          <div className="text-xs text-gray-500">{instance.component_id}</div>
        </div>
        <HealthBadge health={instance.health} />
      </div>

      {instance.web_uis.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {instance.web_uis.map((ui) => (
            <button
              key={ui.name}
              onClick={(e) => {
                e.stopPropagation();
                setActiveFrame({ name: ui.name, path: ui.proxy_url });
              }}
              className="px-2 py-0.5 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700 hover:bg-blue-100"
            >
              {ui.name}
            </button>
          ))}
        </div>
      )}

      {instance.has_terminal && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onOpenTerminal(instance.node_id);
          }}
          className="px-2 py-0.5 bg-gray-800 text-white rounded text-xs hover:bg-gray-700 mb-2"
        >
          Terminal
        </button>
      )}

      {instance.quick_actions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {instance.quick_actions.map((qa) => (
            <span
              key={qa.label}
              className="px-2 py-0.5 bg-gray-100 border border-gray-200 rounded text-xs text-gray-600"
              title={qa.command}
            >
              {qa.label}
            </span>
          ))}
        </div>
      )}

      {activeFrame && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="w-4/5 h-4/5 flex flex-col bg-white rounded-lg overflow-hidden shadow-xl">
            <WebUIFrame
              path={activeFrame.path}
              name={activeFrame.name}
              onClose={() => setActiveFrame(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
