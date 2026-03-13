import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { ComponentNodeData } from "../../../types";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { proxyUrl } from "../../../api/client";

export default function ComponentNode({ id, data }: NodeProps) {
  const nodeData = data as ComponentNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, activeDemoId } = useDemoStore();

  const healthColors: Record<string, string> = {
    healthy: "bg-green-500",
    starting: "bg-yellow-400",
    degraded: "bg-orange-400",
    error: "bg-red-500",
    stopped: "bg-gray-400",
  };

  const handleDoubleClick = () => {
    if (!activeDemoId) return;
    const instance = instances.find((i) => i.node_id === id);
    if (instance && instance.web_uis.length > 0) {
      window.open(proxyUrl(instance.web_uis[0].proxy_url), "_blank");
    }
  };

  return (
    <div
      className="bg-white border-2 border-gray-300 rounded-lg shadow-sm px-4 py-3 min-w-[140px] cursor-pointer hover:border-blue-400 transition-colors"
      onClick={() => setSelectedNode(id)}
      onDoubleClick={handleDoubleClick}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2">
        <div className="text-2xl">📦</div>
        <div>
          <div className="font-semibold text-sm text-gray-800">{nodeData.label}</div>
          <div className="text-xs text-gray-500">{nodeData.variant}</div>
        </div>
        {nodeData.health && (
          <span
            className={`ml-auto w-2.5 h-2.5 rounded-full ${healthColors[nodeData.health] ?? "bg-gray-400"}`}
            title={nodeData.health}
          />
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
