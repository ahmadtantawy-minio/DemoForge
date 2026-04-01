import { type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";

interface StickyNoteData {
  title?: string;
  text: string;
  color?: string;
}

export default function StickyNoteNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as StickyNoteData;
  const color = nodeData.color || "#eab308";
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);

  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={120}
        minHeight={80}
        lineClassName="!border-yellow-500/40"
        handleClassName="!w-2 !h-2 !bg-yellow-500 !border-yellow-500 !rounded-sm"
      />
      <div
        className="w-full h-full rounded-lg p-3 cursor-pointer shadow-sm"
        style={{
          background: `${color}18`,
          borderLeft: `3px solid ${color}80`,
        }}
        onClick={() => setSelectedNode(id)}
      >
        {nodeData.title && (
          <div className="text-xs font-semibold text-foreground mb-1.5 truncate" style={{ color }}>
            {nodeData.title}
          </div>
        )}
        <pre className="text-xs text-foreground whitespace-pre-wrap font-sans leading-relaxed m-0">
          {nodeData.text || "Double-click to edit in properties panel"}
        </pre>
      </div>
    </>
  );
}
