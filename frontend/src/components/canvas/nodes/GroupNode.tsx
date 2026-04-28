import { useState } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";

interface GroupNodeData {
  label: string;
  description?: string;
  color?: string;
  style?: string;
  mode?: string;
}

export default function GroupNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as GroupNodeData;
  const color = nodeData.color || "#3b82f6";
  const [hovered, setHovered] = useState(false);
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);

  return (
    <>
      <NodeResizer
        isVisible={selected || hovered}
        minWidth={200}
        minHeight={150}
        lineClassName="!border-primary/40"
        handleClassName="!w-2.5 !h-2.5 !bg-primary !border-primary !rounded-sm"
      />
      <div
        className="w-full h-full rounded-xl p-3 cursor-pointer relative"
        style={{
          background: `${color}0a`,
          border: `1.5px dashed ${color}40`,
          borderRadius: "12px",
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => setSelectedNode(id)}
      >
        {/* Handles so edges (e.g. GPU server → MinIO tiers) resolve; RF needs anchors on group nodes */}
        <Handle type="target" position={Position.Top} id="group-in-top" className="!opacity-0 !w-2 !h-2" />
        <Handle type="target" position={Position.Left} id="group-in-left" className="!opacity-0 !w-2 !h-2" />
        <Handle
          type="source"
          position={Position.Bottom}
          id="group-bottom-out"
          className="!opacity-0 !w-2 !h-2 !left-1/2 !-translate-x-1/2"
        />
        <Handle type="source" position={Position.Right} id="group-right-out" className="!opacity-0 !w-2 !h-2" />
        <div
          className="font-semibold text-xs uppercase tracking-wider [color:color-mix(in_srgb,var(--group-accent)_34%,#0c0a12)] dark:[color:color-mix(in_srgb,var(--group-accent)_78%,#fafafa)]"
          style={{ ["--group-accent" as string]: color }}
        >
          {nodeData.label || "Group"}
        </div>
        {nodeData.mode === "cluster" && (
          <div className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary/10 text-primary">
            Cluster
          </div>
        )}
        {nodeData.description && (
          <div className="text-[10px] text-muted-foreground mt-0.5">{nodeData.description}</div>
        )}
      </div>
    </>
  );
}
