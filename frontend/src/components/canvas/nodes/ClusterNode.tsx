import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import ComponentIcon from "../../shared/ComponentIcon";

interface ClusterNodeData {
  label: string;
  componentId: string;
  nodeCount: number;
  drivesPerNode: number;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: string;
}

export default function ClusterNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as ClusterNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, setActiveView } = useDemoStore();
  const nodeCount = nodeData.nodeCount || 4;
  const drivesPerNode = nodeData.drivesPerNode || 1;

  // Find running instances matching this cluster's synthetic nodes
  const clusterInstances = instances.filter((i) => i.node_id.startsWith(`${id}-node-`));
  const healthyCount = clusterInstances.filter((i) => i.health === "healthy").length;

  const handleNodeClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveView("control-plane");
  };

  return (
    <>
      <NodeResizer isVisible={selected} minWidth={240} minHeight={160} />
      <div
        className="w-full h-full rounded-xl p-4 cursor-pointer border-2 border-primary/30 bg-primary/5"
        onClick={() => setSelectedNode(id)}
      >
        <Handle type="target" position={Position.Left} />
        <div className="flex items-center gap-2 mb-3">
          <ComponentIcon icon={nodeData.componentId || "minio"} size={24} />
          <div className="flex-1">
            <div className="font-semibold text-sm text-foreground">
              {nodeData.label || "MinIO Cluster"}
            </div>
            <div className="text-[10px] text-muted-foreground">
              {nodeCount} nodes × {drivesPerNode} drive
              {drivesPerNode > 1 ? "s" : ""} • erasure coded
            </div>
          </div>
          {clusterInstances.length > 0 && (
            <div className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
              healthyCount === clusterInstances.length
                ? "bg-green-500/15 text-green-400"
                : healthyCount > 0
                ? "bg-yellow-500/15 text-yellow-400"
                : "bg-red-500/15 text-red-400"
            }`}>
              {healthyCount}/{clusterInstances.length}
            </div>
          )}
        </div>
        {/* Internal node visualization — clickable to go to Instances view */}
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: nodeCount }).map((_, i) => {
            const inst = clusterInstances.find((c) => c.node_id === `${id}-node-${i + 1}`);
            const isHealthy = inst?.health === "healthy";
            return (
              <div
                key={i}
                className={`w-8 h-8 rounded border flex items-center justify-center transition-colors cursor-pointer hover:border-primary ${
                  inst
                    ? isHealthy
                      ? "bg-green-500/10 border-green-500/30"
                      : "bg-red-500/10 border-red-500/30"
                    : "bg-card border-border"
                }`}
                title={inst ? `${inst.node_id} (${inst.health}) — click for details` : `Node ${i + 1} (not deployed)`}
                onClick={handleNodeClick}
              >
                <ComponentIcon
                  icon={nodeData.componentId || "minio"}
                  size={14}
                />
              </div>
            );
          })}
        </div>
        <Handle type="source" position={Position.Right} />
      </div>
    </>
  );
}
