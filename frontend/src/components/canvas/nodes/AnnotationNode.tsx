import { useState, useCallback, useEffect } from "react";
import { type NodeProps, Handle, Position, useReactFlow, NodeResizer } from "@xyflow/react";
import type { AnnotationNodeData } from "../../../types";
import { useDiagramStore } from "../../../stores/diagramStore";


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

const fontSizeClass: Record<string, string> = {
  sm: "text-sm",
  base: "text-base",
  lg: "text-lg",
  xl: "text-xl",
};

export default function AnnotationNode({ data, id, selected }: NodeProps) {
  const d = data as unknown as AnnotationNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(d.title || "");
  const [editBody, setEditBody] = useState(d.body || "");
  const [editStyle, setEditStyle] = useState<AnnotationNodeData["style"]>(d.style || "info");
  const { setNodes } = useReactFlow();

  // Listen for programmatic edit trigger (e.g. from context menu)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ id: string }>).detail;
      if (detail.id === id) {
        setEditTitle(d.title || "");
        setEditBody(d.body || "");
        setEditStyle(d.style || "info");
        setIsEditing(true);
      }
    };
    document.addEventListener("annotation:edit", handler);
    return () => document.removeEventListener("annotation:edit", handler);
  }, [id, d.title, d.body, d.style]);

  const startEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setEditTitle(d.title || "");
    setEditBody(d.body || "");
    setEditStyle(d.style || "info");
    setIsEditing(true);
  }, [d.title, d.body, d.style]);

  const saveEdit = useCallback(() => {
    setNodes((nodes) =>
      nodes.map((n) =>
        n.id === id
          ? { ...n, data: { ...n.data, title: editTitle, body: editBody, style: editStyle } }
          : n
      )
    );
    useDiagramStore.getState().setDirty(true);
    setIsEditing(false);
  }, [id, editTitle, editBody, editStyle, setNodes]);

  const cancelEdit = useCallback(() => {
    setIsEditing(false);
  }, []);

  if (isEditing) {
    return (
      <div
        className={`nodrag rounded-lg px-4 py-3 ${styleClasses[editStyle] || styleClasses.info}`}
        style={{ width: d.width || 300 }}
        onDoubleClick={(e) => e.stopPropagation()}
      >
        <Handle type="source" position={Position.Bottom} className="!w-0 !h-0 !border-0 !bg-transparent !min-w-0 !min-h-0" />
        <input
          autoFocus
          className="w-full bg-transparent text-sm font-semibold mb-2 outline-none border-b border-current/20 pb-1 placeholder:text-muted-foreground/50"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          placeholder="Title"
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Escape") cancelEdit();
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") saveEdit();
          }}
        />
        <textarea
          className="w-full bg-transparent text-xs text-muted-foreground resize-none outline-none leading-relaxed mb-3 placeholder:text-muted-foreground/50"
          rows={4}
          value={editBody}
          onChange={(e) => setEditBody(e.target.value)}
          placeholder="Description... (supports **bold**)"
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Escape") cancelEdit();
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") saveEdit();
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <select
            className="text-[10px] bg-background/60 border border-border rounded px-1.5 py-0.5 text-foreground"
            value={editStyle}
            onChange={(e) => setEditStyle(e.target.value as AnnotationNodeData["style"])}
          >
            <option value="info">Info</option>
            <option value="callout">Callout</option>
            <option value="warning">Warning</option>
            <option value="step">Step</option>
          </select>
          <div className="flex gap-1">
            <button
              className="text-[10px] px-2 py-0.5 rounded bg-muted text-muted-foreground hover:bg-accent transition-colors"
              onClick={cancelEdit}
            >
              Cancel
            </button>
            <button
              className="text-[10px] px-2 py-0.5 rounded bg-primary text-primary-foreground hover:bg-primary/80 transition-colors"
              onClick={saveEdit}
            >
              Save
            </button>
          </div>
        </div>
      </div>
    );
  }

  const textSize = fontSizeClass[d.fontSize || "sm"];

  return (
    <>
      <NodeResizer
        isVisible={selected}
        minWidth={160}
        minHeight={60}
        lineClassName="!border-blue-400/40"
        handleClassName="!w-2 !h-2 !bg-blue-400 !border-blue-400 !rounded-sm"
      />
      <div
        className={`w-full h-full rounded-lg border-0 px-4 py-3 cursor-grab active:cursor-grabbing ${styleClasses[d.style] || styleClasses.info}`}
        onClick={() => setSelectedNode(id)}
        onDoubleClick={startEdit}
      >
        {/* Hidden handles for annotation-pointer edges */}
        <Handle type="source" position={Position.Bottom} className="!w-0 !h-0 !border-0 !bg-transparent !min-w-0 !min-h-0" />
        {d.style === "step" && d.stepNumber != null && (
          <div className="w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xs font-semibold mb-2">
            {d.stepNumber}
          </div>
        )}
        {d.title && (
          <div className={`${textSize} font-semibold mb-1`}>{d.title}</div>
        )}
        {d.body && (
          <div className={`${textSize} text-muted-foreground leading-relaxed whitespace-pre-line`}>
            {renderAnnotationBody(d.body)}
          </div>
        )}
      </div>
    </>
  );
}
