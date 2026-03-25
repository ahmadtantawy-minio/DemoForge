import { useCallback, useRef, useState, useEffect } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useReactFlow,
  type Node,
  type Edge,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import { toast } from "sonner";
import { saveDiagram, fetchDemo, fetchComponents, activateEdgeConfig, pauseEdgeConfig, resyncEdge } from "../../api/client";
import ComponentNode from "./nodes/ComponentNode";
import GroupNode from "./nodes/GroupNode";
import StickyNoteNode from "./nodes/StickyNoteNode";
import ClusterNode from "./nodes/ClusterNode";
import AnimatedDataEdge from "./edges/AnimatedDataEdge";
import ConnectionTypePicker from "./ConnectionTypePicker";
import NodeContextMenu from "./nodes/NodeContextMenu";
import MinioAdminPanel from "../minio/MinioAdminPanel";
import SqlEditorPanel from "../sql/SqlEditorPanel";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { MousePointerClick, Group } from "lucide-react";

const nodeTypes = { component: ComponentNode, group: GroupNode, sticky: StickyNoteNode, cluster: ClusterNode };
const edgeTypes = { data: AnimatedDataEdge, animated: AnimatedDataEdge };

let nodeCounter = 0;
let groupCounter = 0;

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
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode, setNodes, setEdges, setSelectedEdge, setComponentManifests } = useDiagramStore();
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

  // Fetch component manifests for connection validation
  useEffect(() => {
    fetchComponents()
      .then((res) => {
        const manifests: Record<string, any> = {};
        for (const c of res.components) {
          if (c.connections) {
            manifests[c.id] = c.connections;
          }
        }
        setComponentManifests(manifests);
      })
      .catch(() => {});
  }, [setComponentManifests]);

  const reactFlowInstance = useReactFlow();
  const { deleteElements } = reactFlowInstance;
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edgeId: string; confirm: boolean } | null>(null);
  const [selectionMenu, setSelectionMenu] = useState<{ x: number; y: number } | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [pendingDelete, setPendingDelete] = useState<{ type: "node" | "edge"; ids: string[] } | null>(null);
  const [adminPanel, setAdminPanel] = useState<{ clusterId: string; clusterLabel: string; defaultTab?: string } | null>(null);
  const [sqlEditorPanel, setSqlEditorPanel] = useState<{ scenarioId: string } | null>(null);

  // Track selected nodes for multi-select grouping
  const onSelectionChange = useCallback(({ nodes: selectedNodes }: OnSelectionChangeParams) => {
    setSelectedNodeIds(selectedNodes.filter((n) => n.type !== "group").map((n) => n.id));
  }, []);

  // Right-click on a multi-selection to show "Create Group" option
  const onSelectionContextMenu = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    const componentSelection = selectedNodeIds.filter((id) => {
      const n = useDiagramStore.getState().nodes.find((node) => node.id === id);
      return n && n.type !== "group";
    });
    if (componentSelection.length >= 2) {
      setSelectionMenu({ x: event.clientX, y: event.clientY });
    }
  }, [selectedNodeIds]);

  // Load diagram from backend when active demo changes
  useEffect(() => {
    if (!activeDemoId) return;
    fetchDemo(activeDemoId).then((demo) => {
      if (!demo) return;
      // Load groups as React Flow group nodes
      const rfGroups = (demo.groups || []).map((g: any) => ({
        id: g.id,
        type: "group",
        position: g.position || { x: 0, y: 0 },
        style: { width: g.width || 400, height: g.height || 300 },
        data: { label: g.label, description: g.description || "", color: g.color || "#3b82f6", style: g.style || "solid", mode: g.mode || "visual", cluster_config: g.cluster_config || {} },
      }));
      const rfClusters = (demo.clusters || []).map((c: any) => ({
        id: c.id,
        type: "cluster",
        position: c.position || { x: 0, y: 0 },
        style: { width: c.width || 280, height: c.height || 200 },
        data: {
          label: c.label || "MinIO Cluster",
          componentId: c.component || "minio",
          nodeCount: c.node_count || 4,
          drivesPerNode: c.drives_per_node || 1,
          credentials: c.credentials || {},
          config: c.config || {},
          mcpEnabled: c.mcp_enabled !== false,
          aistorTablesEnabled: c.aistor_tables_enabled === true,
        },
      }));
      const rfStickies = (demo.sticky_notes || []).map((s: any) => ({
        id: s.id,
        type: "sticky",
        position: s.position || { x: 0, y: 0 },
        style: { width: s.width || 200, height: s.height || 120 },
        data: { text: s.text || "", color: s.color || "#eab308" },
      }));
      const rfNodes = (demo.nodes || []).map((n: any) => ({
        id: n.id,
        type: "component",
        position: n.position || { x: 0, y: 0 },
        ...(n.group_id ? { parentId: n.group_id } : {}),
        data: {
          label: n.component,
          componentId: n.component,
          variant: n.variant,
          config: n.config || {},
          networks: n.networks || {},
          displayName: n.display_name || "",
          labels: n.labels || {},
          groupId: n.group_id || null,
        },
      }));
      const rfEdges = (demo.edges || []).map((e: any) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.source_handle || undefined,
        targetHandle: e.target_handle || undefined,
        type: "animated",
        data: {
          connectionType: e.connection_type,
          network: e.network,
          label: e.label || "",
          status: "idle",
          connectionConfig: e.connection_config || {},
          autoConfigure: e.auto_configure ?? true,
        },
      }));
      // Derive nodeCounter from all node/cluster/group IDs to avoid collisions
      const trailingNum = (id: string): number => {
        const m = id.match(/(\d+)$/);
        return m ? parseInt(m[1], 10) : 0;
      };
      const allIds = [
        ...rfNodes.map((n: any) => n.id),
        ...rfClusters.map((c: any) => c.id),
        ...rfGroups.map((g: any) => g.id),
        ...rfStickies.map((s: any) => s.id),
      ];
      nodeCounter = allIds.reduce((max: number, id: string) => Math.max(max, trailingNum(id)), 0);
      // Derive groupCounter from existing group IDs
      const maxGroupId = rfGroups.reduce((max: number, g: any) => {
        const num = parseInt(g.id.replace("group-", "") || "0", 10);
        return isNaN(num) ? max : Math.max(max, num);
      }, 0);
      groupCounter = maxGroupId;
      setNodes([...rfGroups, ...rfClusters, ...rfStickies, ...rfNodes]);
      setEdges(rfEdges);
    }).catch(() => {});
  }, [activeDemoId, setNodes, setEdges]);

  const debouncedSave = useRef(
    debounce((demoId: string, ns: Node[], es: Edge[]) => {
      // Separate groups from component nodes for saving
      const groups = ns.filter((n) => n.type === "group");
      const componentNodes = ns.filter((n) => n.type !== "group");
      saveDiagram(demoId, [...componentNodes, ...groups], es).catch(() => {});
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

  const handleEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      setSelectedEdge(edge.id);
    },
    [setSelectedEdge]
  );

  const handleEdgeContextMenu = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      event.preventDefault();
      setEdgeContextMenu({ x: event.clientX, y: event.clientY, edgeId: edge.id, confirm: false });
      setContextMenu(null);
      setSelectionMenu(null);
    },
    []
  );

  const handleDeleteEdge = useCallback(
    (edgeId: string) => {
      deleteElements({ edges: [{ id: edgeId }] });
      setEdgeContextMenu(null);
      if (activeDemoId) {
        const state = useDiagramStore.getState();
        debouncedSave(activeDemoId, state.nodes, state.edges);
      }
    },
    [deleteElements, activeDemoId, debouncedSave]
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (isRunning) return;

      const isGroup = e.dataTransfer.getData("isGroup") === "true";
      const isSticky = e.dataTransfer.getData("isSticky") === "true";
      const isCluster = e.dataTransfer.getData("isCluster") === "true";
      const componentId = e.dataTransfer.getData("componentId");
      const variant = e.dataTransfer.getData("variant") || "single";
      const label = e.dataTransfer.getData("label") || componentId;

      if (!componentId && !isGroup && !isSticky && !isCluster) return;

      const bounds = (e.target as HTMLDivElement).closest(".react-flow")?.getBoundingClientRect();
      const x = bounds ? e.clientX - bounds.left - 70 : e.clientX;
      const y = bounds ? e.clientY - bounds.top - 30 : e.clientY;

      if (isGroup) {
        groupCounter += 1;
        const newGroup: Node = {
          id: `group-${groupCounter}`,
          type: "group",
          position: { x, y },
          style: { width: 400, height: 300 },
          data: {
            label: "New Group",
            description: "",
            color: "#3b82f6",
            style: "solid",
          },
        };
        addNode(newGroup);
        if (activeDemoId) {
          const state = useDiagramStore.getState();
          debouncedSave(activeDemoId, [...state.nodes, newGroup], state.edges);
        }
        return;
      }

      if (isSticky) {
        nodeCounter += 1;
        const newSticky: Node = {
          id: `note-${nodeCounter}`,
          type: "sticky",
          position: { x, y },
          style: { width: 200, height: 120 },
          data: {
            text: "",
            color: "#eab308",
          },
        };
        addNode(newSticky);
        if (activeDemoId) {
          const state = useDiagramStore.getState();
          debouncedSave(activeDemoId, [...state.nodes, newSticky], state.edges);
        }
        return;
      }

      if (isCluster) {
        nodeCounter += 1;
        const newCluster: Node = {
          id: `minio-cluster-${nodeCounter}`,
          type: "cluster",
          position: { x, y },
          style: { width: 280, height: 200 },
          data: {
            label: "MinIO Cluster",
            componentId: "minio",
            nodeCount: 2,
            drivesPerNode: 1,
            credentials: { root_user: "minioadmin", root_password: "minioadmin" },
            config: {},
            mcpEnabled: true,
            aistorTablesEnabled: false,
          },
        };
        addNode(newCluster);
        if (activeDemoId) {
          const state = useDiagramStore.getState();
          debouncedSave(activeDemoId, [...state.nodes, newCluster], state.edges);
        }
        return;
      }

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

  // Create a group from selected nodes
  const handleCreateGroupFromSelection = useCallback(() => {
    const state = useDiagramStore.getState();
    const selectedNodes = state.nodes.filter(
      (n) => selectedNodeIds.includes(n.id) && n.type !== "group"
    );
    if (selectedNodes.length < 2) return;

    // Compute bounding box of selected nodes
    const NODE_WIDTH = 140;
    const NODE_HEIGHT = 60;
    const PADDING = 40;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of selectedNodes) {
      let absX = n.position.x;
      let absY = n.position.y;
      if (n.parentId) {
        const parent = state.nodes.find((p) => p.id === n.parentId);
        if (parent) {
          absX += parent.position.x;
          absY += parent.position.y;
        }
      }
      minX = Math.min(minX, absX);
      minY = Math.min(minY, absY);
      maxX = Math.max(maxX, absX + NODE_WIDTH);
      maxY = Math.max(maxY, absY + NODE_HEIGHT);
    }

    const groupX = minX - PADDING;
    const groupY = minY - PADDING - 20;
    const groupW = maxX - minX + PADDING * 2;
    const groupH = maxY - minY + PADDING * 2 + 20;

    groupCounter += 1;
    const groupId = `group-${groupCounter}`;

    const newGroup: Node = {
      id: groupId,
      type: "group",
      position: { x: groupX, y: groupY },
      style: { width: Math.max(groupW, 200), height: Math.max(groupH, 150) },
      data: {
        label: "New Group",
        description: "",
        color: "#3b82f6",
        style: "solid",
      },
    };

    // Update child nodes: set parentId and convert positions to relative
    const updatedNodes = state.nodes.map((n) => {
      if (!selectedNodeIds.includes(n.id) || n.type === "group") return n;
      let absX = n.position.x;
      let absY = n.position.y;
      if (n.parentId) {
        const parent = state.nodes.find((p) => p.id === n.parentId);
        if (parent) {
          absX += parent.position.x;
          absY += parent.position.y;
        }
      }
      return {
        ...n,
        parentId: groupId,
        position: { x: absX - groupX, y: absY - groupY },
        extent: "parent" as const,
        data: { ...n.data, groupId },
      };
    });

    // Insert group before its children (React Flow requirement)
    const childIds = new Set(selectedNodeIds);
    const nonChildren = updatedNodes.filter((n) => !childIds.has(n.id));
    const children = updatedNodes.filter((n) => childIds.has(n.id));
    const finalNodes = [
      ...nonChildren.filter((n) => n.type === "group"),
      newGroup,
      ...nonChildren.filter((n) => n.type !== "group"),
      ...children,
    ];

    setNodes(finalNodes);
    setSelectionMenu(null);

    if (activeDemoId) {
      debouncedSave(activeDemoId, finalNodes, state.edges);
    }
  }, [selectedNodeIds, setNodes, activeDemoId, debouncedSave]);

  // B5: Handle node drag stop — detect drag into/out of groups
  const onNodeDragStop = useCallback((_event: React.MouseEvent, draggedNode: Node) => {
    if (draggedNode.type === "group") return;

    const state = useDiagramStore.getState();
    const groups = state.nodes.filter((n) => n.type === "group");
    if (groups.length === 0) return;

    // Get absolute position of dragged node
    let absX = draggedNode.position.x;
    let absY = draggedNode.position.y;
    if (draggedNode.parentId) {
      const parent = state.nodes.find((p) => p.id === draggedNode.parentId);
      if (parent) {
        absX += parent.position.x;
        absY += parent.position.y;
      }
    }

    const NODE_WIDTH = 140;
    const NODE_HEIGHT = 60;
    const nodeCenterX = absX + NODE_WIDTH / 2;
    const nodeCenterY = absY + NODE_HEIGHT / 2;

    // Check if node center is inside any group
    let targetGroup: Node | null = null;
    for (const g of groups) {
      const gw = (g.style?.width as number) || 400;
      const gh = (g.style?.height as number) || 300;
      if (
        nodeCenterX >= g.position.x &&
        nodeCenterX <= g.position.x + gw &&
        nodeCenterY >= g.position.y &&
        nodeCenterY <= g.position.y + gh
      ) {
        targetGroup = g;
        break;
      }
    }

    const currentParent = draggedNode.parentId || null;

    if (targetGroup && currentParent === targetGroup.id) {
      // Node is still in same group — no change needed
      return;
    }

    if (targetGroup && currentParent !== targetGroup.id) {
      // Node dragged INTO a (different) group
      const updatedNodes = state.nodes.map((n) => {
        if (n.id !== draggedNode.id) return n;
        return {
          ...n,
          parentId: targetGroup!.id,
          extent: "parent" as const,
          position: { x: absX - targetGroup!.position.x, y: absY - targetGroup!.position.y },
          data: { ...n.data, groupId: targetGroup!.id },
        };
      });
      // Ensure group appears before its children
      const reordered = [
        ...updatedNodes.filter((n) => n.type === "group"),
        ...updatedNodes.filter((n) => n.type !== "group"),
      ];
      setNodes(reordered);
      if (activeDemoId) debouncedSave(activeDemoId, reordered, state.edges);
      return;
    }

    if (!targetGroup && currentParent) {
      // Node dragged OUT of a group
      const updatedNodes = state.nodes.map((n) => {
        if (n.id !== draggedNode.id) return n;
        const { parentId, extent, ...rest } = n as any;
        return {
          ...rest,
          position: { x: absX, y: absY },
          data: { ...n.data, groupId: null },
        };
      });
      setNodes(updatedNodes);
      if (activeDemoId) debouncedSave(activeDemoId, updatedNodes, state.edges);
    }
  }, [setNodes, activeDemoId, debouncedSave]);

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
      // Ctrl/Cmd+G: create group from selection
      if ((e.metaKey || e.ctrlKey) && e.key === "g") {
        e.preventDefault();
        const state = useDiagramStore.getState();
        const selected = state.nodes.filter((n: any) => n.selected && n.type !== "group");
        if (selected.length >= 2) {
          handleCreateGroupFromSelection();
        }
        return;
      }
      // Backspace/Delete disabled — use context menu instead (avoids conflict with text inputs)
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [isRunning]);

  useEffect(() => {
    const handler = () => {
      setContextMenu(null);
      setEdgeContextMenu(null);
      setSelectionMenu(null);
    };
    if (contextMenu || selectionMenu) window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [contextMenu, selectionMenu]);

  return (
    <div className="w-full h-full relative" onDrop={onDrop} onDragOver={onDragOver}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        onEdgeClick={handleEdgeClick}
        onEdgeContextMenu={handleEdgeContextMenu}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeContextMenu={onNodeContextMenu}
        onSelectionContextMenu={onSelectionContextMenu}
        onSelectionChange={onSelectionChange}
        onNodeDragStop={onNodeDragStop}
        colorMode={isDark ? "dark" : "light"}
        deleteKeyCode={null}
        fitView
      >
        <MiniMap />
        <Controls />
        <Background />
      </ReactFlow>

      {/* Connection type picker overlay */}
      <ConnectionTypePicker />

      {/* Empty canvas guidance */}
      {nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
          <MousePointerClick className="w-10 h-10 text-muted-foreground/30 mb-3" />
          <p className="text-sm text-muted-foreground/60">
            Drag components from the palette to start building your demo
          </p>
        </div>
      )}

      {contextMenu && (() => {
        // For cluster nodes, use the embedded LB for web UIs, but node-1 for terminal
        const ctxNode = nodes.find((n) => n.id === contextMenu.nodeId);
        const isCluster = ctxNode?.type === "cluster";
        let instance = instances.find((i) => i.node_id === contextMenu.nodeId);
        if (!instance && isCluster) {
          instance = instances.find((i) => i.node_id === `${contextMenu.nodeId}-lb`);
        }
        const terminalNodeId = isCluster ? `${contextMenu.nodeId}-node-1` : contextMenu.nodeId;
        return (
          <NodeContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            nodeId={contextMenu.nodeId}
            componentId={(ctxNode?.data as any)?.componentId}
            isCluster={isCluster}
            clusterLabel={isCluster ? (ctxNode?.data as any)?.label : undefined}
            mcpEnabled={isCluster ? (ctxNode?.data as any)?.mcpEnabled !== false : false}
            instance={instance}
            demoId={activeDemoId ?? ""}
            nodeConfig={(ctxNode?.data as any)?.config}
            onOpenAdmin={isCluster ? () => setAdminPanel({ clusterId: contextMenu.nodeId, clusterLabel: (ctxNode?.data as any)?.label || contextMenu.nodeId, defaultTab: "overview" }) : undefined}
            onOpenMcpTools={isCluster ? () => setAdminPanel({ clusterId: contextMenu.nodeId, clusterLabel: (ctxNode?.data as any)?.label || contextMenu.nodeId, defaultTab: "mcp-tools" }) : undefined}
            onOpenAiChat={isCluster ? () => setAdminPanel({ clusterId: contextMenu.nodeId, clusterLabel: (ctxNode?.data as any)?.label || contextMenu.nodeId, defaultTab: "ai-chat" }) : undefined}
            onOpenSqlEditor={(ctxNode?.data as any)?.componentId === "trino" ? () => setSqlEditorPanel({ scenarioId: "ecommerce-orders" }) : undefined}
            isRunning={isRunning}
            onOpenTerminal={() => onOpenTerminal(terminalNodeId)}
            onDeleteNode={handleDeleteNode}
            onClose={() => setContextMenu(null)}
          />
        );
      })()}

      {/* Edge context menu */}
      {edgeContextMenu && (() => {
        const edge = edges.find((e) => e.id === edgeContextMenu.edgeId);
        const edgeData = edge?.data as any;
        const configStatus = edgeData?.configStatus;
        const connType = edgeData?.connectionType || "";
        const isClusterEdge = connType.startsWith("cluster-");
        const activateLabel =
          connType === "cluster-site-replication" ? "Activate Site Replication" :
          connType === "cluster-tiering" ? "Activate Tiering" :
          "Activate Replication";
        const pauseLabel =
          connType === "cluster-site-replication" ? "Remove Site Replication" :
          connType === "cluster-tiering" ? "Remove Tiering" :
          "Pause Replication";
        return (
          <div
            className="fixed z-50 bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[160px] text-popover-foreground"
            style={{
              top: Math.min(edgeContextMenu.y, window.innerHeight - 150),
              left: Math.min(edgeContextMenu.x, window.innerWidth - 200),
            }}
          >
            <div className="px-3 py-1.5 text-xs font-semibold text-muted-foreground border-b border-border">
              {edgeData?.label || connType || "Connection"}
              {configStatus && (
                <span className={`ml-2 text-[10px] ${
                  configStatus === "applied" ? "text-green-400" :
                  configStatus === "failed" ? "text-red-400" :
                  configStatus === "pending" ? "text-yellow-400" :
                  "text-muted-foreground"
                }`}>
                  ({configStatus})
                </span>
              )}
            </div>
            {isClusterEdge && activeDemoId && isRunning && configStatus !== "applied" && configStatus !== "pending" && (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-green-400 hover:bg-green-500/10 transition-colors"
                onClick={() => {
                  toast.info("Activating connection...");
                  activateEdgeConfig(activeDemoId, edgeContextMenu.edgeId)
                    .then((r) => {
                      if (r.status === "applied") toast.success("Connection activated");
                      else toast.error("Activation failed", {
                        description: r.error?.slice(0, 200),
                        duration: 10000,
                        action: r.error ? { label: "Copy", onClick: () => navigator.clipboard.writeText(r.error!) } : undefined,
                      });
                    })
                    .catch((e: any) => toast.error("Activation failed", {
                      description: e.message?.slice(0, 200),
                      duration: 10000,
                      action: { label: "Copy", onClick: () => navigator.clipboard.writeText(e.message) },
                    }));
                  setEdgeContextMenu(null);
                }}
              >
                {activateLabel}
              </button>
            )}
            {isClusterEdge && activeDemoId && configStatus === "applied" && (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-yellow-400 hover:bg-yellow-500/10 transition-colors"
                onClick={() => {
                  pauseEdgeConfig(activeDemoId, edgeContextMenu.edgeId)
                    .then(() => toast.info("Connection paused"))
                    .catch((e: any) => toast.error("Failed", { description: e.message }));
                  setEdgeContextMenu(null);
                }}
              >
                {pauseLabel}
              </button>
            )}
            {isClusterEdge && activeDemoId && isRunning && connType.includes("site-replication") && configStatus === "applied" && (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
                onClick={() => {
                  toast.info("Starting resync...");
                  resyncEdge(activeDemoId, edgeContextMenu.edgeId)
                    .then((r) => {
                      if (r.status === "resync_started") toast.success("Resync started");
                      else toast.error("Resync failed", {
                        description: r.error?.slice(0, 200),
                        duration: 10000,
                        action: r.error ? { label: "Copy", onClick: () => navigator.clipboard.writeText(r.error!) } : undefined,
                      });
                    })
                    .catch((e: any) => toast.error("Resync failed", {
                      description: e.message?.slice(0, 200),
                      duration: 10000,
                      action: { label: "Copy", onClick: () => navigator.clipboard.writeText(e.message) },
                    }));
                  setEdgeContextMenu(null);
                }}
              >
                Resync All Sites
              </button>
            )}
            {!edgeContextMenu.confirm ? (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                onClick={() => setEdgeContextMenu({ ...edgeContextMenu, confirm: true })}
              >
                Delete Connection
              </button>
            ) : (
              <div className="px-3 py-1.5 flex items-center gap-2">
                <span className="text-xs text-destructive">Delete?</span>
                <button
                  className="px-2 py-0.5 text-xs bg-destructive text-destructive-foreground rounded hover:bg-destructive/80"
                  onClick={() => handleDeleteEdge(edgeContextMenu.edgeId)}
                >
                  Yes
                </button>
                <button
                  className="px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded hover:bg-accent"
                  onClick={() => setEdgeContextMenu(null)}
                >
                  No
                </button>
              </div>
            )}
          </div>
        );
      })()}

      {/* Selection context menu for multi-select grouping */}
      {selectionMenu && (
        <div
          className="fixed z-50 bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[160px] text-popover-foreground"
          style={{
            top: Math.min(selectionMenu.y, window.innerHeight - 100),
            left: Math.min(selectionMenu.x, window.innerWidth - 200),
          }}
        >
          <div className="px-3 py-1.5 text-xs font-semibold text-muted-foreground border-b border-border">
            {selectedNodeIds.length} nodes selected
          </div>
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors flex items-center gap-2"
            onClick={() => handleCreateGroupFromSelection()}
          >
            <Group className="w-4 h-4" />
            Create Group
          </button>
        </div>
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

      {adminPanel && (
        <MinioAdminPanel
          open={!!adminPanel}
          onOpenChange={(open) => { if (!open) setAdminPanel(null); }}
          clusterId={adminPanel.clusterId}
          clusterLabel={adminPanel.clusterLabel}
          defaultTab={(adminPanel.defaultTab as any) || "overview"}
        />
      )}

      {sqlEditorPanel && activeDemoId && (
        <SqlEditorPanel
          open={!!sqlEditorPanel}
          onOpenChange={(open) => { if (!open) setSqlEditorPanel(null); }}
          demoId={activeDemoId}
          scenarioId={sqlEditorPanel.scenarioId}
        />
      )}
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
