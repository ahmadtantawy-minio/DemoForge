import { useState } from "react";
import { type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";

interface GroupNodeData {
  label: string;
  description?: string;
  color?: string;
  style?: string;
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
        className="w-full h-full rounded-xl p-3 cursor-pointer"
        style={{
          background: `${color}0a`,
          borderRadius: "12px",
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => setSelectedNode(id)}
      >
        <div className="font-semibold text-xs uppercase tracking-wider" style={{ color: `${color}cc` }}>
          {nodeData.label || "Group"}
        </div>
        {nodeData.description && (
          <div className="text-[10px] text-muted-foreground mt-0.5">{nodeData.description}</div>
        )}
      </div>
    </>
  );
}
