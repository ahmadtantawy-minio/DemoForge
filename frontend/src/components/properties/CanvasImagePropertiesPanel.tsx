import { useState } from "react";
import type { Edge, Node } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CANVAS_IMAGE_PRESETS } from "../../lib/canvasImagePresets";
import { saveDiagram } from "../../api/client";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface CanvasImagePropertiesPanelProps {
  selectedNodeId: string;
  selectedNode: Node;
  nodes: Node[];
  edges: Edge[];
  setNodes: (nodes: Node[]) => void;
  /** Raw setNodes without marking dirty — used for delete + persist */
  replaceNodesRaw: (nodes: Node[]) => void;
  setDirty: (dirty: boolean) => void;
  activeDemoId: string | null;
}

export function CanvasImagePropertiesPanel({
  selectedNodeId,
  selectedNode,
  nodes,
  edges,
  setNodes,
  replaceNodesRaw,
  setDirty,
  activeDemoId,
}: CanvasImagePropertiesPanelProps) {
  const [deleteImageOpen, setDeleteImageOpen] = useState(false);
  const imgData = selectedNode.data as Record<string, unknown>;
  const updateImage = (patch: Record<string, unknown>) => {
    setNodes(
      nodes.map((n) => {
        if (n.id !== selectedNodeId) return n;
        const extra = patch.locked !== undefined ? { draggable: !patch.locked } : {};
        return { ...n, ...extra, data: { ...n.data, ...patch } };
      })
    );
  };
  const changePreset = (newImageId: string) => {
    const preset = CANVAS_IMAGE_PRESETS.find((p) => p.id === newImageId);
    setNodes(
      nodes.map((n) => {
        if (n.id !== selectedNodeId) return n;
        return {
          ...n,
          style: preset ? { width: preset.defaultWidth, height: preset.defaultHeight } : n.style,
          data: { ...n.data, image_id: newImageId },
        };
      })
    );
  };
  const performDeleteImage = () => {
    const newNodes = nodes.filter((n) => n.id !== selectedNodeId);
    replaceNodesRaw(newNodes);
    setDirty(true);
    setDeleteImageOpen(false);
    if (activeDemoId) {
      saveDiagram(activeDemoId, newNodes, edges).catch(() => {});
    }
  };
  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Image</div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Image</label>
        <Select value={(imgData.image_id as string) ?? ""} onValueChange={changePreset}>
          <SelectTrigger className="h-8 text-sm">
            <SelectValue placeholder="Select visual" />
          </SelectTrigger>
          <SelectContent>
            {CANVAS_IMAGE_PRESETS.map((preset) => (
              <SelectItem key={preset.id} value={preset.id}>
                {preset.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Label</label>
        <Input
          type="text"
          value={(imgData.label as string) ?? ""}
          onChange={(e) => updateImage({ label: e.target.value })}
          className="h-8 text-sm"
          placeholder="Image label"
        />
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">
          Opacity — {Math.round(((imgData.opacity as number) ?? 1) * 100)}%
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(((imgData.opacity as number) ?? 1) * 100)}
          onChange={(e) => updateImage({ opacity: parseInt(e.target.value, 10) / 100 })}
          className="w-full accent-primary"
        />
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Layer</label>
        <div className="flex gap-1">
          {(["background", "foreground"] as const).map((layer) => (
            <button
              key={layer}
              type="button"
              onClick={() => updateImage({ layer })}
              className={`flex-1 py-1 text-xs rounded border transition-colors ${
                ((imgData.layer as string) ?? "background") === layer
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-border hover:bg-accent"
              }`}
            >
              {layer.charAt(0).toUpperCase() + layer.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={(imgData.locked as boolean) ?? false}
            onChange={(e) => updateImage({ locked: e.target.checked })}
            className="rounded border-border"
          />
          <span className="text-xs text-foreground">Lock position</span>
        </label>
      </div>

      <div className="pt-3 border-t border-border">
        <button
          type="button"
          onClick={() => setDeleteImageOpen(true)}
          className="w-full py-1.5 text-xs font-medium rounded border border-destructive/50 text-destructive bg-destructive/5 hover:bg-destructive/10 transition-colors"
        >
          Delete Image
        </button>
      </div>

      <AlertDialog open={deleteImageOpen} onOpenChange={setDeleteImageOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete image?</AlertDialogTitle>
            <AlertDialogDescription>
              Remove this canvas image from the diagram. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={performDeleteImage}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
