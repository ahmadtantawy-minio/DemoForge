import { type NodeProps, Handle, Position } from "@xyflow/react";
import type { AnnotationNodeData } from "../../../types";

const styleClasses: Record<string, string> = {
  info: "bg-blue-50/80 dark:bg-blue-950/30 border-l-2 border-l-blue-400",
  callout: "bg-amber-50/80 dark:bg-amber-950/30 border-l-2 border-l-amber-400",
  warning: "bg-red-50/80 dark:bg-red-950/30 border-l-2 border-l-red-400",
  step: "bg-background/90 border border-border shadow-sm",
};

function renderAnnotationBody(text: string) {
  return text.split("\n").map((line, i, arr) => (
    <span key={i}>
      {line.split(/(\*\*.*?\*\*)/).map((part, j) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={j} className="font-medium text-foreground">
            {part.slice(2, -2)}
          </strong>
        ) : (
          part
        )
      )}
      {i < arr.length - 1 && <br />}
    </span>
  ));
}

export default function AnnotationNode({ data }: NodeProps) {
  const d = data as unknown as AnnotationNodeData;

  return (
    <div
      className={`rounded-lg border-0 px-4 py-3 cursor-grab active:cursor-grabbing ${styleClasses[d.style] || styleClasses.info}`}
      style={{ width: d.width || 300 }}
    >
      {/* Hidden handles for annotation-pointer edges */}
      <Handle type="source" position={Position.Bottom} className="!w-0 !h-0 !border-0 !bg-transparent !min-w-0 !min-h-0" />
      {d.style === "step" && d.stepNumber != null && (
        <div className="w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xs font-semibold mb-2">
          {d.stepNumber}
        </div>
      )}
      {d.title && (
        <div className="text-sm font-semibold mb-1">{d.title}</div>
      )}
      {d.body && (
        <div className="text-xs text-muted-foreground leading-relaxed whitespace-pre-line">
          {renderAnnotationBody(d.body)}
        </div>
      )}
    </div>
  );
}
