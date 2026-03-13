import { useCallback, useRef } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import { saveDiagram } from "../../api/client";
import ComponentNode from "./nodes/ComponentNode";
import DataEdge from "./edges/DataEdge";

const nodeTypes = { component: ComponentNode };
const edgeTypes = { data: DataEdge };

let nodeCounter = 0;

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}

export default function DiagramCanvas() {
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode } = useDiagramStore();
  const activeDemoId = useDemoStore((s) => s.activeDemoId);

  const debouncedSave = useRef(
    debounce((demoId: string, ns: Node[], es: any[]) => {
      saveDiagram(demoId, ns, es).catch(() => {});
    }, 500)
  ).current;

  const handleNodesChange = useCallback(
    (changes: any) => {
      onNodesChange(changes);
      if (activeDemoId) {
        debouncedSave(activeDemoId, useDiagramStore.getState().nodes, useDiagramStore.getState().edges);
      }
    },
    [onNodesChange, activeDemoId, debouncedSave]
  );

  const handleEdgesChange = useCallback(
    (changes: any) => {
      onEdgesChange(changes);
      if (activeDemoId) {
        debouncedSave(activeDemoId, useDiagramStore.getState().nodes, useDiagramStore.getState().edges);
      }
    },
    [onEdgesChange, activeDemoId, debouncedSave]
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const componentId = e.dataTransfer.getData("componentId");
      const variant = e.dataTransfer.getData("variant") || "single";
      const label = e.dataTransfer.getData("label") || componentId;
      if (!componentId) return;

      const bounds = (e.target as HTMLDivElement).closest(".react-flow")?.getBoundingClientRect();
      const x = bounds ? e.clientX - bounds.left - 70 : e.clientX;
      const y = bounds ? e.clientY - bounds.top - 30 : e.clientY;

      nodeCounter += 1;
      const newNode: Node = {
        id: `${componentId}-${nodeCounter}`,
        type: "component",
        position: { x, y },
        data: {
          label,
          componentId,
          variant,
          config: {},
        },
      };
      addNode(newNode);
      if (activeDemoId) {
        const state = useDiagramStore.getState();
        debouncedSave(activeDemoId, [...state.nodes, newNode], state.edges);
      }
    },
    [addNode, activeDemoId, debouncedSave]
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  return (
    <div className="w-full h-full" onDrop={onDrop} onDragOver={onDragOver}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
      >
        <MiniMap />
        <Controls />
        <Background />
      </ReactFlow>
    </div>
  );
}
