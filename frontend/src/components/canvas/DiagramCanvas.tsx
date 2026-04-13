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
import { toast } from "../../lib/toast";
import { saveDiagram, saveLayout, fetchDemo, fetchComponents, activateEdgeConfig, pauseEdgeConfig, resyncEdge } from "../../api/client";
import ComponentNode from "./nodes/ComponentNode";
import GroupNode from "./nodes/GroupNode";
import StickyNoteNode from "./nodes/StickyNoteNode";
import ClusterNode from "./nodes/ClusterNode";
import AnnotationNode from "./nodes/AnnotationNode";
import SchematicNode from "./nodes/SchematicNode";
import AnimatedDataEdge from "./edges/AnimatedDataEdge";
import AnnotationPointerEdge from "./edges/AnnotationPointerEdge";
import ConnectionTypePicker from "./ConnectionTypePicker";
import NodeContextMenu from "./nodes/NodeContextMenu";
import LogViewer from "../logs/LogViewer";
import MinioAdminPanel from "../minio/MinioAdminPanel";
import McpPanel from "../minio/McpPanel";
import SqlEditorPanel from "../sql/SqlEditorPanel";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { MousePointerClick, Group, Save, Check, X, Loader2, Copy, Clipboard } from "lucide-react";

const nodeTypes = { component: ComponentNode, group: GroupNode, sticky: StickyNoteNode, cluster: ClusterNode, annotation: AnnotationNode, schematic: SchematicNode };
const edgeTypes = { data: AnimatedDataEdge, animated: AnimatedDataEdge, "annotation-pointer": AnnotationPointerEdge };

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
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode, setNodes, setEdges, setSelectedEdge, setComponentManifests, setDirty, clipboard, setClipboard } = useDiagramStore();
  const { activeDemoId, instances, demos } = useDemoStore();
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isRunning = activeDemo?.status === "running";
  const isExperience = activeDemo?.mode === "experience";

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
  // Experience mode visibility toggles
  const [showAnnotations, setShowAnnotations] = useState(true);
  const [showSchematics, setShowSchematics] = useState(true);
  const [layoutSaveStatus, setLayoutSaveStatus] = useState<"" | "saving" | "saved" | "error">("");

  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edgeId: string; confirm: boolean } | null>(null);
  const [selectionMenu, setSelectionMenu] = useState<{ x: number; y: number } | null>(null);
  const [paneMenu, setPaneMenu] = useState<{ x: number; y: number } | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [pendingDelete, setPendingDelete] = useState<{ type: "node" | "edge"; ids: string[] } | null>(null);
  const [adminPanel, setAdminPanel] = useState<{ clusterId: string; clusterLabel: string; defaultTab?: string } | null>(null);
  const [mcpPanel, setMcpPanel] = useState<{ clusterId: string; clusterLabel: string; defaultTab?: "mcp-tools" | "ai-chat" } | null>(null);
  const [sqlEditorPanel, setSqlEditorPanel] = useState<{ scenarioId: string } | null>(null);
  const [logViewer, setLogViewer] = useState<{ nodeId: string; componentId?: string } | null>(null);

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
        width: c.width || 380,
        style: { width: c.width || 380 },
        data: {
          label: c.label || "MinIO Cluster",
          componentId: c.component || "minio",
          nodeCount: c.node_count || 4,
          drivesPerNode: c.drives_per_node || 4,
          credentials: c.credentials || {},
          config: c.config || {},
          mcpEnabled: c.mcp_enabled !== false,
          aistorTablesEnabled: c.aistor_tables_enabled === true,
          ecParity: c.ec_parity ?? 3,
          ecParityUpgradePolicy: c.ec_parity_upgrade_policy ?? "upgrade",
          diskSizeTb: c.disk_size_tb ?? 1,
          // Map server_pools (backend snake_case) → serverPools (frontend camelCase)
          // Without this, migrateClusterData recreates a default single pool on every load,
          // discarding any multi-pool or customised pool configuration.
          serverPools: (c.server_pools || []).map((p: any) => ({
            id: p.id,
            nodeCount: p.node_count,
            drivesPerNode: p.drives_per_node,
            diskSizeTb: p.disk_size_tb ?? 1,
            diskType: p.disk_type ?? "ssd",
            ecParity: p.ec_parity ?? 3,
            ecParityUpgradePolicy: p.ec_parity_upgrade_policy ?? "upgrade",
            volumePath: p.volume_path ?? "/data",
          })),
        },
      }));
      const rfStickies = (demo.sticky_notes || []).map((s: any) => ({
        id: s.id,
        type: "sticky",
        position: s.position || { x: 0, y: 0 },
        style: { width: s.width || 200, height: s.height || 120 },
        data: { text: s.text || "", color: s.color || "#eab308" },
      }));
      const isExp = demo.mode === "experience";
      const rfAnnotations = (demo.annotations || []).map((a: any) => ({
        id: a.id,
        type: "annotation",
        position: a.position || { x: 0, y: 0 },
        draggable: true,  // Always draggable — cosmetic repositioning
        selectable: true,
        deletable: !isExp,
        data: {
          title: a.title || "",
          body: a.body || "",
          style: a.style || "info",
          stepNumber: a.step_number,
          width: a.width || 300,
          pointerTarget: a.pointer_target,
        },
      }));
      // Create annotation pointer edges
      const rfAnnotationEdges = (demo.annotations || [])
        .filter((a: any) => a.pointer_target)
        .map((a: any) => ({
          id: `ann-${a.id}-ptr`,
          source: a.id,
          target: a.pointer_target,
          type: "annotation-pointer",
        }));
      const rfSchematics = (demo.schematics || []).map((s: any) => ({
        id: s.id,
        type: "schematic",
        position: s.position || { x: 0, y: 0 },
        ...(s.parent_group ? { parentId: s.parent_group, extent: "parent" as const } : {}),
        draggable: true,
        selectable: false,
        deletable: false,
        connectable: false,
        data: {
          label: s.label,
          sublabel: s.sublabel || "",
          variant: s.variant || "generic",
          children: s.children || [],
          width: s.width,
          height: s.height,
        },
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
          protocol: e.protocol || "",
          latency: e.latency || "",
          bandwidth: e.bandwidth || "",
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
      // Auto-migrate legacy nginx edge types (failover/load-balance) to unified nginx-backend
      const allLoadedNodes = [...rfNodes, ...rfClusters, ...rfGroups, ...rfStickies, ...rfSchematics, ...rfAnnotations];
      const migratedEdges = rfEdges.map((edge: any) => {
        if (edge.data?.connectionType === "failover" || edge.data?.connectionType === "load-balance") {
          const srcNode = allLoadedNodes.find((n: any) => n.id === edge.source);
          const tgtNode = allLoadedNodes.find((n: any) => n.id === edge.target);
          const srcIsNginx = (srcNode?.data as any)?.componentId === "nginx";
          const tgtIsNginx = (tgtNode?.data as any)?.componentId === "nginx";
          if (srcIsNginx || tgtIsNginx) {
            return { ...edge, data: { ...edge.data, connectionType: "nginx-backend" } };
          }
        }
        return edge;
      });
      // Auto-migrate nginx nodes: variant=failover-proxy → config.mode=failover; variant=load-balancer → config.mode=round-robin
      const migratedNodes = rfNodes.map((node: any) => {
        if ((node.data as any)?.componentId === "nginx") {
          const variant = (node.data as any)?.variant;
          const hasMode = !!(node.data as any)?.config?.mode;
          if (!hasMode && variant === "failover-proxy") {
            return { ...node, data: { ...node.data, config: { ...(node.data.config || {}), mode: "failover" }, variant: "" } };
          }
          if (!hasMode && variant === "load-balancer") {
            return { ...node, data: { ...node.data, config: { ...(node.data.config || {}), mode: "round-robin" }, variant: "" } };
          }
        }
        return node;
      });
      setNodes([...rfGroups, ...rfClusters, ...rfStickies, ...rfAnnotations, ...rfSchematics, ...migratedNodes]);
      setEdges([...migratedEdges, ...rfAnnotationEdges]);
      setDirty(false);
    }).catch(() => {});
  }, [activeDemoId, setNodes, setEdges, setDirty]);

  const debouncedSave = useRef(
    debounce((demoId: string, ns: Node[], es: Edge[]) => {
      // Separate groups from component nodes for saving
      const groups = ns.filter((n) => n.type === "group");
      const componentNodes = ns.filter((n) => n.type !== "group");
      saveDiagram(demoId, [...componentNodes, ...groups], es).catch(() => {});
    }, 500)
  ).current;

  // Layout save for experience mode (positions only)
  const layoutSaveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doLayoutSave = useCallback((demoId: string) => {
    if (layoutSaveTimeout.current) clearTimeout(layoutSaveTimeout.current);
    layoutSaveTimeout.current = setTimeout(() => {
      const ns = useDiagramStore.getState().nodes;
      const positions = ns.map((n) => ({ id: n.id, x: n.position.x, y: n.position.y }));
      setLayoutSaveStatus("saving");
      saveLayout(demoId, positions)
        .then(() => {
          setLayoutSaveStatus("saved");
          setTimeout(() => setLayoutSaveStatus(""), 2000);
        })
        .catch(() => {
          setLayoutSaveStatus("error");
          setTimeout(() => setLayoutSaveStatus(""), 3000);
        });
    }, 1000);
  }, []);

  const handleNodesChange = useCallback(
    (changes: any) => {
      if (isExperience) {
        // Allow position (drag), selection, and dimension changes — block add/remove
        const allowed = changes.filter((c: any) =>
          c.type === "position" || c.type === "select" || c.type === "dimensions"
        );
        if (allowed.length > 0) onNodesChange(allowed);
        // Save layout on any position change (debounced)
        if (activeDemoId && allowed.some((c: any) => c.type === "position")) {
          doLayoutSave(activeDemoId);
        }
        return;
      }
      if (isRunning) {
        // When running: allow position/select/dimensions only — block remove/add
        const allowed = changes.filter((c: any) =>
          c.type === "position" || c.type === "select" || c.type === "dimensions"
        );
        if (allowed.length > 0) onNodesChange(allowed);
        return;
      }
      onNodesChange(changes);
      if (activeDemoId) {
        setDirty(true);
      }
    },
    [onNodesChange, activeDemoId, setDirty, doLayoutSave, isExperience, isRunning]
  );

  const handleEdgesChange = useCallback(
    (changes: any) => {
      if (isExperience) {
        const allowed = changes.filter((c: any) => c.type === "select");
        if (allowed.length > 0) onEdgesChange(allowed);
        return;
      }
      onEdgesChange(changes);
      if (activeDemoId) {
        setDirty(true);
      }
    },
    [onEdgesChange, activeDemoId, setDirty, isExperience]
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
        setDirty(true);
      }
    },
    [deleteElements, activeDemoId, setDirty]
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      if (isRunning || isExperience) return;

      const isGroup = e.dataTransfer.getData("isGroup") === "true";
      const isSticky = e.dataTransfer.getData("isSticky") === "true";
      const isAnnotation = e.dataTransfer.getData("isAnnotation") === "true";
      const isCluster = e.dataTransfer.getData("isCluster") === "true";
      const componentId = e.dataTransfer.getData("componentId");
      const variant = e.dataTransfer.getData("variant") || "single";
      const label = e.dataTransfer.getData("label") || componentId;

      if (!componentId && !isGroup && !isSticky && !isCluster && !isAnnotation) return;

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
          saveDiagram(activeDemoId, [...state.nodes, newGroup], state.edges).then(() => setDirty(false)).catch(() => {});
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
          saveDiagram(activeDemoId, [...state.nodes, newSticky], state.edges).then(() => setDirty(false)).catch(() => {});
        }
        return;
      }

      if (isAnnotation) {
        nodeCounter += 1;
        const newAnnotation: Node = {
          id: `annotation-${nodeCounter}`,
          type: "annotation",
          position: { x, y },
          data: {
            title: "Annotation",
            body: "Add your description here...",
            style: "info",
            width: 260,
          },
        };
        addNode(newAnnotation);
        if (activeDemoId) {
          const state = useDiagramStore.getState();
          saveDiagram(activeDemoId, [...state.nodes, newAnnotation], state.edges).then(() => setDirty(false)).catch(() => {});
        }
        return;
      }

      if (isCluster) {
        nodeCounter += 1;
        const newCluster: Node = {
          id: `minio-cluster-${nodeCounter}`,
          type: "cluster",
          position: { x, y },
          style: { width: 380, height: 200 },
          data: {
            label: "MinIO Cluster",
            componentId: "minio",
            credentials: { root_user: "minioadmin", root_password: "minioadmin" },
            config: {},
            mcpEnabled: true,
            aistorTablesEnabled: false,
            serverPools: [
              {
                id: "pool-1",
                nodeCount: 2,
                drivesPerNode: 4,
                diskSizeTb: 4,
                diskType: "nvme",
                ecParity: 2,
                ecParityUpgradePolicy: "upgrade",
                volumePath: "/data",
              },
            ],
          },
        };
        addNode(newCluster);
        if (activeDemoId) {
          const state = useDiagramStore.getState();
          saveDiagram(activeDemoId, [...state.nodes, newCluster], state.edges).then(() => setDirty(false)).catch(() => {});
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
        saveDiagram(activeDemoId, [...state.nodes, newNode], state.edges).then(() => setDirty(false)).catch(() => {});
      }
    },
    [addNode, activeDemoId, setDirty, isRunning]
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
      setDirty(true);
    }
  }, [selectedNodeIds, setNodes, activeDemoId, setDirty]);

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
      if (activeDemoId) setDirty(true);
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
      if (activeDemoId) setDirty(true);
    }
  }, [setNodes, activeDemoId, setDirty]);

  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: any) => {
    event.preventDefault();
    setContextMenu({ x: event.clientX, y: event.clientY, nodeId: node.id });
  }, []);

  // Delete a node and all connected edges via context menu
  const handleDeleteNode = useCallback((nodeId: string) => {
    setPendingDelete({ type: "node", ids: [nodeId] });
  }, []);

  const handleCopyNode = useCallback((nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (node) setClipboard(node);
  }, [nodes, setClipboard]);

  const handlePaste = useCallback(() => {
    if (!clipboard) return;
    nodeCounter += 1;
    const base = (clipboard.data as any)?.componentId || clipboard.id.replace(/-\d+$/, "");
    const newId = `${base}-${nodeCounter}`;
    const offset = 40;
    const newNode: Node = {
      ...clipboard,
      id: newId,
      position: { x: clipboard.position.x + offset, y: clipboard.position.y + offset },
      selected: false,
      data: { ...((clipboard.data as any) || {}), componentId: base },
    };
    addNode(newNode);
    setPaneMenu(null);
    if (activeDemoId) {
      const state = useDiagramStore.getState();
      saveDiagram(activeDemoId, [...state.nodes, newNode], state.edges).then(() => setDirty(false)).catch(() => {});
    }
  }, [clipboard, addNode, activeDemoId, setDirty]);

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
        setDirty(true);
      }, 50);
    }
  }, [pendingDelete, deleteElements, activeDemoId, setDirty]);

  // Intercept Backspace/Delete key — show confirmation instead of immediate delete
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl/Cmd+S: save diagram
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        const { isDirty, setDirty: sd } = useDiagramStore.getState();
        if (!isDirty || !activeDemoId) return;
        const { nodes: ns, edges: es } = useDiagramStore.getState();
        const groups = ns.filter((n) => n.type === "group");
        const componentNodes = ns.filter((n) => n.type !== "group");
        saveDiagram(activeDemoId, [...componentNodes, ...groups], es)
          .then(() => { sd(false); toast.success("Saved", { duration: 1500 }); })
          .catch(() => { toast.error("Failed to save diagram"); });
        return;
      }
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
      // L: open log viewer for selected node (running only)
      if (e.key === "l" || e.key === "L") {
        if (isRunning && selectedNodeIds.length === 1) {
          const selectedNode = useDiagramStore.getState().nodes.find((n: any) => n.id === selectedNodeIds[0]);
          if (selectedNode && (selectedNode.type === "component" || selectedNode.type === "cluster")) {
            e.preventDefault();
            setLogViewer({ nodeId: selectedNodeIds[0], componentId: (selectedNode.data as any)?.componentId });
          }
        }
        return;
      }
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [isRunning, selectedNodeIds]);

  useEffect(() => {
    const handler = () => {
      setContextMenu(null);
      setEdgeContextMenu(null);
      setSelectionMenu(null);
      setPaneMenu(null);
    };
    if (contextMenu || selectionMenu || paneMenu) window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [contextMenu, selectionMenu, paneMenu]);

  // Also close NodeContextMenu when canvas:close-menus fires (same event that closes ClusterNode menus)
  useEffect(() => {
    const handler = () => setContextMenu(null);
    window.addEventListener("canvas:close-menus", handler);
    return () => window.removeEventListener("canvas:close-menus", handler);
  }, []);

  // Filter nodes/edges by visibility toggles in experience mode
  const visibleNodes = isExperience
    ? nodes.filter((n) => {
        if (n.type === "annotation" && !showAnnotations) return false;
        if (n.type === "schematic" && !showSchematics) return false;
        return true;
      })
    : nodes;
  const hiddenAnnotationIds = new Set(
    nodes.filter((n) => n.type === "annotation" && !showAnnotations).map((n) => n.id)
  );
  const visibleEdges = isExperience
    ? edges.filter((e) => {
        if (e.type === "annotation-pointer") return showAnnotations;
        if (hiddenAnnotationIds.has(e.source) || hiddenAnnotationIds.has(e.target)) return false;
        return true;
      })
    : edges;

  return (
    <div className="w-full h-full relative" onDrop={onDrop} onDragOver={onDragOver}>
      {/* Experience mode banner + toggles */}
      {isExperience && (
        <div className="absolute top-2 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2">
          <div className="bg-purple-500/15 border border-purple-500/30 text-purple-300 text-xs px-3 py-1.5 rounded-full backdrop-blur-sm">
            Experience mode
          </div>
          <button
            onClick={() => setShowAnnotations(!showAnnotations)}
            className={`text-[11px] px-2.5 py-1 rounded-full border backdrop-blur-sm transition-all ${
              showAnnotations
                ? "bg-blue-500/15 border-blue-500/30 text-blue-300"
                : "bg-zinc-500/10 border-zinc-500/30 text-zinc-500"
            }`}
          >
            {showAnnotations ? "Hide" : "Show"} Annotations
          </button>
          <button
            onClick={() => setShowSchematics(!showSchematics)}
            className={`text-[11px] px-2.5 py-1 rounded-full border backdrop-blur-sm transition-all ${
              showSchematics
                ? "bg-purple-500/15 border-purple-500/30 text-purple-300"
                : "bg-zinc-500/10 border-zinc-500/30 text-zinc-500"
            }`}
          >
            {showSchematics ? "Hide" : "Show"} GPU Internals
          </button>
        </div>
      )}
      {/* Save indicator — top right */}
      {isExperience && layoutSaveStatus && (
        <div className="absolute top-2 right-2 z-50 flex items-center gap-1.5 px-2 py-1 rounded-md backdrop-blur-sm border transition-all text-[11px]"
          style={{
            background: layoutSaveStatus === "saving" ? "rgba(234,179,8,0.1)" : layoutSaveStatus === "saved" ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
            borderColor: layoutSaveStatus === "saving" ? "rgba(234,179,8,0.3)" : layoutSaveStatus === "saved" ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
            color: layoutSaveStatus === "saving" ? "#eab308" : layoutSaveStatus === "saved" ? "#22c55e" : "#ef4444",
          }}
        >
          {layoutSaveStatus === "saving" && <Loader2 className="w-3 h-3 animate-spin" />}
          {layoutSaveStatus === "saved" && <Check className="w-3 h-3" />}
          {layoutSaveStatus === "error" && <X className="w-3 h-3" />}
          {layoutSaveStatus === "saving" ? "Saving" : layoutSaveStatus === "saved" ? "Saved" : "Failed"}
        </div>
      )}
      <ReactFlow
        nodes={visibleNodes}
        edges={visibleEdges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={isExperience || isRunning ? undefined : onConnect}
        onEdgeClick={handleEdgeClick}
        onEdgeContextMenu={isExperience ? undefined : handleEdgeContextMenu}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeContextMenu={onNodeContextMenu}
        onSelectionContextMenu={isExperience ? undefined : onSelectionContextMenu}
        onSelectionChange={onSelectionChange}
        onNodeDragStop={isExperience ? undefined : onNodeDragStop}
        onPaneClick={() => {
          window.dispatchEvent(new CustomEvent("canvas:close-menus"));
        }}
        onPaneContextMenu={(e) => {
          e.preventDefault();
          setPaneMenu({ x: e.clientX, y: e.clientY });
        }}
        colorMode={isDark ? "dark" : "light"}
        deleteKeyCode={null}
        nodesDraggable={true}
        nodesConnectable={!isExperience}
        elementsSelectable={true}
        fitView
      >
        <MiniMap style={{ width: 120, height: 80 }} />
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
        const isAnnotation = ctxNode?.type === "annotation";

        if (isAnnotation) {
          return (
            <div
              className="fixed z-50 bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[160px] text-popover-foreground"
              style={{ top: Math.min(contextMenu.y, window.innerHeight - 100), left: Math.min(contextMenu.x, window.innerWidth - 200) }}
            >
              <div className="px-3 py-1.5 text-xs font-semibold text-muted-foreground border-b border-border">Annotation</div>
              <button
                className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors"
                onClick={() => {
                  document.dispatchEvent(new CustomEvent("annotation:edit", { detail: { id: contextMenu.nodeId } }));
                  setContextMenu(null);
                }}
              >
                Edit
              </button>
              <div className="border-t border-border mt-1 pt-1">
                <button
                  className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                  onClick={() => { handleDeleteNode(contextMenu.nodeId); setContextMenu(null); }}
                >
                  Delete Annotation
                </button>
              </div>
            </div>
          );
        }

        const isCluster = ctxNode?.type === "cluster";
        let instance = instances.find((i) => i.node_id === contextMenu.nodeId);
        if (!instance && isCluster) {
          instance = instances.find((i) => i.node_id === `${contextMenu.nodeId}-pool1-node-1`);
        }
        const terminalNodeId = isCluster ? `${contextMenu.nodeId}-pool1-node-1` : contextMenu.nodeId;
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
            onOpenMcpTools={isCluster ? () => setMcpPanel({ clusterId: contextMenu.nodeId, clusterLabel: (ctxNode?.data as any)?.label || contextMenu.nodeId, defaultTab: "mcp-tools" }) : undefined}
            onOpenAiChat={isCluster ? () => setMcpPanel({ clusterId: contextMenu.nodeId, clusterLabel: (ctxNode?.data as any)?.label || contextMenu.nodeId, defaultTab: "ai-chat" }) : undefined}
            onOpenSqlEditor={(ctxNode?.data as any)?.componentId === "trino" ? () => setSqlEditorPanel({ scenarioId: "ecommerce-orders" }) : undefined}
            isRunning={isRunning}
            onOpenTerminal={() => onOpenTerminal(terminalNodeId)}
            onDeleteNode={handleDeleteNode}
            onCopyNode={() => handleCopyNode(contextMenu.nodeId)}
            onViewLogs={() => setLogViewer({ nodeId: contextMenu.nodeId, componentId: (ctxNode?.data as any)?.componentId })}
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
                        action: r.error ? { label: <Copy className="w-3.5 h-3.5" strokeWidth={1.5} />, onClick: () => navigator.clipboard.writeText(r.error!) } : undefined,
                      });
                    })
                    .catch((e: any) => toast.error("Activation failed", {
                      description: e.message?.slice(0, 200),
                      duration: 10000,
                      action: { label: <Copy className="w-3.5 h-3.5" strokeWidth={1.5} />, onClick: () => navigator.clipboard.writeText(e.message) },
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
                        action: r.error ? { label: <Copy className="w-3.5 h-3.5" strokeWidth={1.5} />, onClick: () => navigator.clipboard.writeText(r.error!) } : undefined,
                      });
                    })
                    .catch((e: any) => toast.error("Resync failed", {
                      description: e.message?.slice(0, 200),
                      duration: 10000,
                      action: { label: <Copy className="w-3.5 h-3.5" strokeWidth={1.5} />, onClick: () => navigator.clipboard.writeText(e.message) },
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

      {paneMenu && (
        <div
          className="fixed z-50 bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[160px] text-popover-foreground"
          style={{
            top: Math.min(paneMenu.y, window.innerHeight - 100),
            left: Math.min(paneMenu.x, window.innerWidth - 200),
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 ${clipboard ? "hover:bg-accent hover:text-accent-foreground" : "text-muted-foreground cursor-not-allowed"} transition-colors`}
            onClick={clipboard ? handlePaste : undefined}
            disabled={!clipboard}
          >
            <Clipboard className="w-3.5 h-3.5" />
            Paste
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

      {mcpPanel && activeDemoId && (
        <McpPanel
          open={!!mcpPanel}
          onOpenChange={(open) => { if (!open) setMcpPanel(null); }}
          demoId={activeDemoId}
          clusterId={mcpPanel.clusterId}
          clusterLabel={mcpPanel.clusterLabel}
          defaultTab={mcpPanel.defaultTab}
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

      {logViewer && activeDemoId && (
        <LogViewer
          demoId={activeDemoId}
          nodeId={logViewer.nodeId}
          componentId={logViewer.componentId}
          onClose={() => setLogViewer(null)}
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
