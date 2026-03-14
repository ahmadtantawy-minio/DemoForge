import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
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
  const nodeCount = nodeData.nodeCount || 4;
  const drivesPerNode = nodeData.drivesPerNode || 1;

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
          <div>
            <div className="font-semibold text-sm text-foreground">
              {nodeData.label || "MinIO Cluster"}
            </div>
            <div className="text-[10px] text-muted-foreground">
              {nodeCount} nodes × {drivesPerNode} drive
              {drivesPerNode > 1 ? "s" : ""} • erasure coded
            </div>
          </div>
        </div>
        {/* Internal node visualization */}
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: nodeCount }).map((_, i) => (
            <div
              key={i}
              className="w-8 h-8 rounded bg-card border border-border flex items-center justify-center"
            >
              <ComponentIcon
                icon={nodeData.componentId || "minio"}
                size={14}
              />
            </div>
          ))}
        </div>
        <Handle type="source" position={Position.Right} />
      </div>
    </>
  );
}
