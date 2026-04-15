import { type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { getPreset } from "../../../lib/canvasImagePresets";

interface CanvasImageData {
  image_id: string;
  opacity: number;
  layer: "background" | "foreground";
  label: string;
  locked: boolean;
}

export default function CanvasImageNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as CanvasImageData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const preset = getPreset(nodeData.image_id);

  return (
    <>
      <NodeResizer
        isVisible={selected && !nodeData.locked}
        minWidth={60}
        minHeight={20}
        lineClassName="!border-zinc-500/40"
        handleClassName="!w-2 !h-2 !bg-zinc-400 !border-zinc-400 !rounded-sm"
      />
      <div
        className="w-full h-full flex flex-col items-center justify-center cursor-pointer select-none"
        style={{ opacity: nodeData.opacity ?? 0.8 }}
        onClick={() => setSelectedNode(id)}
      >
        {preset ? (
          <img
            src={`/canvas-images/${preset.svgPath}.svg`}
            alt={preset.label}
            className="w-full h-full object-contain"
            draggable={false}
          />
        ) : (
          <div className="text-zinc-500 text-xs">{nodeData.image_id}</div>
        )}
        {nodeData.label && (
          <div className="mt-1 text-xs text-zinc-400 font-medium text-center leading-tight px-1">
            {nodeData.label}
          </div>
        )}
      </div>
    </>
  );
}
