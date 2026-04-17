import type { Node } from "@xyflow/react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface StickyNotePropertiesPanelProps {
  selectedNodeId: string;
  selectedNode: Node;
  nodes: Node[];
  setNodes: (nodes: Node[]) => void;
}

export function StickyNotePropertiesPanel({
  selectedNodeId,
  selectedNode,
  nodes,
  setNodes,
}: StickyNotePropertiesPanelProps) {
  const sData = selectedNode.data as Record<string, unknown>;
  const updateSticky = (patch: Record<string, unknown>) => {
    setNodes(nodes.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n)));
  };
  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Note</div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Title</label>
        <input
          value={(sData.title as string) ?? ""}
          onChange={(e) => updateSticky({ title: e.target.value })}
          className="w-full bg-background border border-input rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Optional title"
        />
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Text</label>
        <textarea
          value={(sData.text as string) ?? ""}
          onChange={(e) => updateSticky({ text: e.target.value })}
          className="w-full bg-background border border-input rounded-md px-3 py-2 text-sm min-h-[120px] resize-y focus:outline-none focus:ring-1 focus:ring-ring font-mono"
          placeholder="Add your notes here..."
        />
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Font Size</label>
        <Select value={(sData.fontSize as string) ?? "sm"} onValueChange={(v) => updateSticky({ fontSize: v })}>
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
        <label className="text-xs text-muted-foreground block mb-1">Visibility</label>
        <div className="flex rounded-md border border-input overflow-hidden">
          {(["customer", "internal"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => {
                if (v === "internal") {
                  updateSticky({ visibility: "internal", color: "#EF9F27" });
                } else {
                  updateSticky({ visibility: "customer" });
                }
              }}
              className={`flex-1 py-1 text-xs transition-colors ${
                ((sData.visibility as string) || "customer") === v
                  ? v === "internal"
                    ? "bg-amber-500/20 text-amber-400 font-medium"
                    : "bg-primary/20 text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              }`}
            >
              {v === "customer" ? "Customer" : "FA internal"}
            </button>
          ))}
        </div>
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Color</label>
        <div className={`flex gap-2 ${sData.visibility === "internal" ? "opacity-40 pointer-events-none" : ""}`}>
          {["#eab308", "#22c55e", "#3b82f6", "#ef4444", "#a855f7", "#f97316"].map((c) => (
            <button
              key={c}
              type="button"
              className={`w-6 h-6 rounded-full border-2 transition-all ${sData.color === c ? "border-foreground scale-110" : "border-transparent"}`}
              style={{ background: c }}
              onClick={() => updateSticky({ color: c })}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
