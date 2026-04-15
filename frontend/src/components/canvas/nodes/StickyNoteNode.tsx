import { type NodeProps, NodeResizer } from "@xyflow/react";
import { Eye } from "lucide-react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";

interface StickyNoteData {
  title?: string;
  text: string;
  color?: string;
  visibility?: "customer" | "internal";
}

export default function StickyNoteNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as StickyNoteData;
  const color = nodeData.color || "#eab308";
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const showFaNotes = useDemoStore((s) => s.showFaNotes);

  const isInternal = nodeData.visibility === "internal";

  const borderColor = isInternal ? "#EF9F27" : `${color}80`;
  const bgColor = isInternal ? "#EF9F2718" : `${color}18`;

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
        style={{
          opacity: isInternal ? (showFaNotes ? 1 : 0) : undefined,
          pointerEvents: isInternal ? (showFaNotes ? "auto" : "none") : undefined,
          transition: isInternal ? "opacity 200ms" : undefined,
        }}
        className="w-full h-full"
      >
        <div
          className="relative w-full h-full rounded-lg p-3 cursor-pointer shadow-sm"
          style={{
            background: bgColor,
            borderLeft: `3px solid ${borderColor}`,
          }}
          onClick={() => setSelectedNode(id)}
        >
          {isInternal && (
            <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 border border-amber-400 text-amber-600 dark:bg-amber-950 dark:border-amber-600 dark:text-amber-400">
              <Eye className="w-2.5 h-2.5" />
              FA only
            </div>
          )}
          {nodeData.title && (
            <div className="text-xs font-semibold text-foreground mb-1.5 truncate" style={{ color: isInternal ? "#EF9F27" : color }}>
              {nodeData.title}
            </div>
          )}
          <pre className="text-xs text-foreground whitespace-pre-wrap font-sans leading-relaxed m-0">
            {nodeData.text || "Double-click to edit in properties panel"}
          </pre>
        </div>
      </div>
    </>
  );
}
