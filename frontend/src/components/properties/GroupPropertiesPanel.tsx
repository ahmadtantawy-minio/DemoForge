import type { Node } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PasswordInput } from "./PasswordInput";

interface GroupPropertiesPanelProps {
  selectedNodeId: string;
  selectedNode: Node;
  nodes: Node[];
  setNodes: (nodes: Node[]) => void;
}

export function GroupPropertiesPanel({ selectedNodeId, selectedNode, nodes, setNodes }: GroupPropertiesPanelProps) {
  const gData = selectedNode.data as Record<string, unknown>;
  const updateGroup = (patch: Record<string, unknown>) => {
    setNodes(nodes.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n)));
  };
  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Group</div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Label</label>
        <Input
          type="text"
          value={(gData.label as string) ?? ""}
          onChange={(e) => updateGroup({ label: e.target.value })}
          className="h-8 text-sm"
        />
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Description</label>
        <textarea
          value={(gData.description as string) ?? ""}
          onChange={(e) => updateGroup({ description: e.target.value })}
          className="w-full bg-background border border-input rounded-md px-3 py-2 text-sm min-h-[60px] resize-y focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Describe this group..."
        />
      </div>
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Color</label>
        <div className="flex gap-2">
          {["#3b82f6", "#22c55e", "#eab308", "#ef4444", "#a855f7", "#f97316", "#06b6d4", "#6b7280"].map((c) => (
            <button
              key={c}
              type="button"
              className={`w-6 h-6 rounded-full border-2 transition-all ${gData.color === c ? "border-foreground scale-110" : "border-transparent"}`}
              style={{ background: c }}
              onClick={() => updateGroup({ color: c })}
            />
          ))}
        </div>
      </div>
      <div className="mb-3 pt-2 border-t border-border">
        <label className="text-xs text-muted-foreground block mb-1">Mode</label>
        <Select value={(gData.mode as string) || "visual"} onValueChange={(v) => updateGroup({ mode: v })}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="visual">Visual (grouping only)</SelectItem>
            <SelectItem value="cluster">Cluster (coordinated deployment)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {gData.mode === "cluster" && (
        <>
          <div className="mb-3">
            <label className="text-xs text-muted-foreground block mb-1">Drives per Node</label>
            <Input
              type="number"
              value={(gData.cluster_config as { drives_per_node?: number } | undefined)?.drives_per_node ?? 1}
              onChange={(e) =>
                updateGroup({
                  cluster_config: {
                    ...((gData.cluster_config as object) || {}),
                    drives_per_node: parseInt(e.target.value, 10) || 1,
                  },
                })
              }
              className="h-8 text-sm"
              min={1}
              max={4}
            />
          </div>
          <div className="mb-3">
            <label className="text-xs text-muted-foreground block mb-1">Root User</label>
            <Input
              type="text"
              value={(gData.cluster_config as { root_user?: string } | undefined)?.root_user ?? "minioadmin"}
              onChange={(e) =>
                updateGroup({
                  cluster_config: {
                    ...((gData.cluster_config as object) || {}),
                    root_user: e.target.value,
                  },
                })
              }
              className="h-8 text-sm"
            />
          </div>
          <div className="mb-3">
            <label className="text-xs text-muted-foreground block mb-1">Root Password</label>
            <PasswordInput
              value={(gData.cluster_config as { root_password?: string } | undefined)?.root_password ?? "minioadmin"}
              onChange={(v) =>
                updateGroup({
                  cluster_config: {
                    ...((gData.cluster_config as object) || {}),
                    root_password: v,
                  },
                })
              }
              className="h-8 text-sm"
            />
          </div>
        </>
      )}
    </div>
  );
}
