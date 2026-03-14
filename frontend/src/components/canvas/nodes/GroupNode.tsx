import { useState } from "react";
import { type NodeProps, NodeResizer } from "@xyflow/react";

interface GroupNodeData {
  label: string;
  description?: string;
  color?: string;
  style?: string;
}

export default function GroupNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as GroupNodeData;
  const color = nodeData.color || "#3b82f6";
  const borderStyle = nodeData.style || "solid";
  const [hovered, setHovered] = useState(false);

  return (
    <>
      <NodeResizer
        isVisible={selected || hovered}
        minWidth={200}
        minHeight={150}
        lineClassName="!border-primary/60"
        handleClassName="!w-2.5 !h-2.5 !bg-primary !border-primary !rounded-sm"
      />
      <div
        className="w-full h-full rounded-xl p-3"
        style={{
          border: `2px ${borderStyle} ${color}40`,
          background: `${color}08`,
          borderRadius: "12px",
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div className="font-bold text-sm text-foreground">{nodeData.label}</div>
        {nodeData.description && (
          <div className="text-xs text-muted-foreground mt-0.5">{nodeData.description}</div>
        )}
      </div>
    </>
  );
}
