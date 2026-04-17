import type { Node } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDiagramStore } from "../../stores/diagramStore";

interface AnnotationPropertiesPanelProps {
  selectedNodeId: string;
  selectedNode: Node;
  nodes: Node[];
  setNodes: (nodes: Node[]) => void;
}

export function AnnotationPropertiesPanel({
  selectedNodeId,
  selectedNode,
  nodes,
  setNodes,
}: AnnotationPropertiesPanelProps) {
  const aData = selectedNode.data as Record<string, unknown>;
  const updateAnnotation = (patch: Record<string, unknown>) => {
    setNodes(nodes.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n)));
    useDiagramStore.getState().setDirty(true);
  };
  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Annotation</div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Title</label>
        <Input
          type="text"
          value={(aData.title as string) ?? ""}
          onChange={(e) => updateAnnotation({ title: e.target.value })}
          className="h-8 text-sm"
          placeholder="Annotation title"
        />
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Body</label>
        <textarea
          value={(aData.body as string) ?? ""}
          onChange={(e) => updateAnnotation({ body: e.target.value })}
          className="w-full bg-background border border-input rounded-md px-3 py-2 text-sm min-h-[100px] resize-y focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Description... (supports **bold**)"
        />
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Font Size</label>
        <Select value={(aData.fontSize as string) ?? "sm"} onValueChange={(v) => updateAnnotation({ fontSize: v })}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sm">Small</SelectItem>
            <SelectItem value="base">Medium</SelectItem>
            <SelectItem value="lg">Large</SelectItem>
            <SelectItem value="xl">Extra Large</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Style</label>
        <Select value={(aData.style as string) ?? "info"} onValueChange={(v) => updateAnnotation({ style: v })}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="info">Info</SelectItem>
            <SelectItem value="callout">Callout</SelectItem>
            <SelectItem value="warning">Warning</SelectItem>
            <SelectItem value="step">Step</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {aData.style === "step" && (
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Step Number</label>
          <Input
            type="number"
            value={(aData.stepNumber as number | undefined) ?? ""}
            onChange={(e) =>
              updateAnnotation({ stepNumber: e.target.value ? parseInt(e.target.value, 10) : undefined })
            }
            className="h-8 text-sm"
            min={1}
            placeholder="e.g. 1"
          />
        </div>
      )}
    </div>
  );
}
