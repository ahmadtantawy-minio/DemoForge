import { useCallback, useRef, useState, useEffect } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useReactFlow,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import { saveDiagram, fetchDemo } from "../../api/client";
import ComponentNode from "./nodes/ComponentNode";
import AnimatedDataEdge from "./edges/AnimatedDataEdge";
import NodeContextMenu from "./nodes/NodeContextMenu";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { MousePointerClick } from "lucide-react";

const nodeTypes = { component: ComponentNode };
const edgeTypes = { data: AnimatedDataEdge, animated: AnimatedDataEdge };

let nodeCounter = 0;

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}

interface DiagramCanvasProps {
  onOpenTerminal: (nodeId: string) => void;
}

function DiagramCanvasInner({ onOpenTerminal }: DiagramCanvasProps) {
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode, setNodes, setEdges } = useDiagramStore();
  const { activeDemoId, instances, demos } = useDemoStore();
  const isRunning = demos.find((d) => d.id === activeDemoId)?.status === "running";

  // Track dark/light theme reactively
  const [isDark, setIsDark] = useState(document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  const { deleteElements } = useReactFlow();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ type: "node" | "edge"; ids: string[] } | null>(null);

  // Load diagram from backend when active demo changes
  useEffect(() => {
    if (!activeDemoId) return;
    fetchDemo(activeDemoId).then((demo) => {
      if (!demo) return;
      const rfNodes = (demo.nodes || []).map((n: any) => ({
        id: n.id,
        type: "component",
        position: n.position || { x: 0, y: 0 },
        data: { label: n.component, componentId: n.component, variant: n.variant, config: n.config || {}, networks: n.networks || {} },
      }));
      const rfEdges = (demo.edges || []).map((e: any) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "animated",
        data: { connectionType: e.connection_type, network: e.network, label: e.label || "", status: "idle" },
      }));
      // Derive nodeCounter from existing node IDs to avoid collisions
      const maxId = rfNodes.reduce((max: number, n: any) => {
        const num = parseInt(n.id.split("-").pop() || "0", 10);
        return isNaN(num) ? max : Math.max(max, num);
      }, 0);
      nodeCounter = maxId;
      setNodes(rfNodes);
      setEdges(rfEdges);
    }).catch(() => {});
  }, [activeDemoId, setNodes, setEdges]);

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
      if (isRunning) return;
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
    [addNode, activeDemoId, debouncedSave, isRunning]
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: any) => {
    event.preventDefault();
    setContextMenu({ x: event.clientX, y: event.clientY, nodeId: node.id });
  }, []);

  // Delete a node and all connected edges via context menu
  const handleDeleteNode = useCallback((nodeId: string) => {
    setPendingDelete({ type: "node", ids: [nodeId] });
  }, []);

  // Confirm deletion
  const confirmDelete = useCallback(() => {
    if (!pendingDelete) return;
    if (pendingDelete.type === "node") {
      const nodeId = pendingDelete.ids[0];
      deleteElements({ nodes: [{ id: nodeId }] });
    } else {
      deleteElements({ edges: pendingDelete.ids.map((id) => ({ id })) });
    }
    setPendingDelete(null);
    if (activeDemoId) {
      setTimeout(() => {
        const s = useDiagramStore.getState();
        debouncedSave(activeDemoId, s.nodes, s.edges);
      }, 50);
    }
  }, [pendingDelete, deleteElements, activeDemoId, debouncedSave]);

  // Intercept Backspace/Delete key — show confirmation instead of immediate delete
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isRunning) return;
      if (e.key === "Backspace" || e.key === "Delete") {
        const selected = useDiagramStore.getState();
        const selectedNodes = selected.nodes.filter((n: any) => n.selected);
        const selectedEdges = selected.edges.filter((edge: any) => edge.selected);
        if (selectedNodes.length > 0) {
          e.preventDefault();
          e.stopPropagation();
          setPendingDelete({ type: "node", ids: selectedNodes.map((n: any) => n.id) });
        } else if (selectedEdges.length > 0) {
          e.preventDefault();
          e.stopPropagation();
          setPendingDelete({ type: "edge", ids: selectedEdges.map((edge: any) => edge.id) });
        }
      }
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [isRunning]);

  useEffect(() => {
    const handler = () => setContextMenu(null);
    if (contextMenu) window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [contextMenu]);

  return (
    <div className="w-full h-full relative" onDrop={onDrop} onDragOver={onDragOver}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeContextMenu={onNodeContextMenu}
        colorMode={isDark ? "dark" : "light"}
        deleteKeyCode={null}
        fitView
      >
        <MiniMap />
        <Controls />
        <Background />
      </ReactFlow>

      {/* Empty canvas guidance */}
      {nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
          <MousePointerClick className="w-10 h-10 text-muted-foreground/30 mb-3" />
          <p className="text-sm text-muted-foreground/60">
            Drag components from the palette to start building your demo
          </p>
        </div>
      )}

      {contextMenu && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          nodeId={contextMenu.nodeId}
          instance={instances.find((i) => i.node_id === contextMenu.nodeId)}
          demoId={activeDemoId ?? ""}
          isRunning={isRunning}
          onOpenTerminal={onOpenTerminal}
          onDeleteNode={handleDeleteNode}
          onClose={() => setContextMenu(null)}
        />
      )}

      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Delete</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.type === "node"
                ? `Delete ${pendingDelete.ids.length > 1 ? `${pendingDelete.ids.length} components` : `"${pendingDelete.ids[0]}"`} and all connected edges?`
                : `Delete ${pendingDelete && pendingDelete.ids.length > 1 ? `${pendingDelete.ids.length} connections` : "this connection"}?`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
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

// Wrap with ReactFlowProvider so useReactFlow() works
import { ReactFlowProvider } from "@xyflow/react";
export default function DiagramCanvas(props: DiagramCanvasProps) {
  return (
    <ReactFlowProvider>
      <DiagramCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
