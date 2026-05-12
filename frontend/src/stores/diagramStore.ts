import { create } from "zustand";
import { Node, Edge, OnNodesChange, OnEdgesChange, applyNodeChanges, applyEdgeChanges, Connection, addEdge } from "@xyflow/react";
import { toast } from "../lib/toast";
import type { ComponentSummary, ConnectionsDef } from "../types";
import {
  canonicalHandlesForClusterEdge,
  CLUSTER_EDGE_TYPES,
  reanchorClusterEdgesTouching,
  reanchorAllClusterPairEdges,
  sanitizeClusterEdgeHandlesForReactFlow,
} from "../lib/clusterConnectionAnchors";
import { findInvalidDiagramEdges } from "../lib/diagramEdgeIssues";

export interface DirectedOption {
  type: string;
  direction: "forward" | "reverse";
  label: string;  // e.g. "MinIO → Trino" or "Trino → MinIO"
}

export interface PendingConnection {
  connection: Connection;
  validTypes: string[];
  directedOptions?: DirectedOption[];  // when present, picker shows direction labels
  sourcePos: { x: number; y: number };
  targetPos: { x: number; y: number };
  /** Cluster↔cluster: human-readable source → target for the picker and default edge pill. */
  clusterFlowLabels?: { sourceLabel: string; targetLabel: string };
  /** When true, picker offers swapping endpoints before choosing a connection type. */
  allowSwapDirection?: boolean;
}

/** Default edge pill label when the connection targets Iceberg browser or S3 file browser. */
function defaultEdgeLabelForTarget(targetId: string | null | undefined, nodes: Node[]): string {
  if (!targetId) return "";
  const node = nodes.find((n) => n.id === targetId);
  const componentId = (node?.data as { componentId?: string } | undefined)?.componentId;
  if (componentId === "iceberg-browser") return "iceberg v4";
  if (componentId === "s3-file-browser") return "S3";
  return "";
}

export type SelectedClusterElement =
  | { type: "cluster" }
  | { type: "pool"; poolId: string }
  | { type: "node"; poolId: string; nodeIndex: number };

interface DiagramState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  selectedClusterElement: SelectedClusterElement | null;
  componentManifests: Record<string, ConnectionsDef>;
  pendingConnection: PendingConnection | null;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  addNode: (node: Node) => void;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  setSelectedClusterElement: (el: SelectedClusterElement | null) => void;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  updateNodeHealth: (nodeId: string, health: string) => void;
  setComponentManifests: (manifests: Record<string, ConnectionsDef>) => void;
  setPendingConnection: (pending: PendingConnection | null) => void;
  /** Swap source/target on the in-progress cluster wire (same handles swapped). */
  swapPendingConnectionDirection: () => void;
  completePendingConnection: (connectionType: string, direction?: "forward" | "reverse") => void;
  isDirty: boolean;
  setDirty: (dirty: boolean) => void;
  clipboard: Node | null;
  setClipboard: (node: Node | null) => void;
  /** In-canvas draggable web UI (e.g. Event Processor event viewer) */
  designerWebUiOverlay: { proxyPath: string; title: string } | null;
  setDesignerWebUiOverlay: (o: { proxyPath: string; title: string } | null) => void;
  /** Central modal target for delete node / delete edge from canvas (DiagramCanvas AlertDialog). */
  editorDeletePrompt: { type: "node" | "edge"; ids: string[] } | null;
  openEditorDeleteDialog: (spec: { type: "node" | "edge"; ids: string[] }) => void;
  closeEditorDeleteDialog: () => void;
  /** Recompute cluster↔cluster edge handles for edges touching this cluster (after moves or bad drags). */
  reanchorClusterEdges: (clusterId: string) => void;
  /** Recompute handles on every cluster↔cluster edge in the diagram. */
  reanchorAllClusterToClusterEdges: () => void;
  /** Fix cluster replication / site / tiering edges whose handles violate React Flow (stops error spam). */
  repairClusterEdgeHandles: () => boolean;
  /** Remove edges by id (e.g. orphaned connections). Returns how many were removed. */
  removeDiagramEdgesByIds: (ids: string[]) => number;
  /** Remove every edge whose source or target node is not on the canvas. Returns how many were removed. */
  pruneInvalidDiagramEdges: () => number;
}

export const useDiagramStore = create<DiagramState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  selectedEdgeId: null,
  selectedClusterElement: null,
  componentManifests: {},
  pendingConnection: null,
  editorDeletePrompt: null,
  openEditorDeleteDialog: (spec) => set({ editorDeletePrompt: spec }),
  closeEditorDeleteDialog: () => set({ editorDeletePrompt: null }),

  reanchorClusterEdges: (clusterId) => {
    const state = get();
    const next = reanchorClusterEdgesTouching(clusterId, state.nodes, state.edges);
    const n = next.reduce((acc, e, i) => {
      const o = state.edges[i];
      if (e.sourceHandle !== o.sourceHandle || e.targetHandle !== o.targetHandle) return acc + 1;
      return acc;
    }, 0);
    set({ edges: next, isDirty: true });
    toast.success("Connection anchors updated", {
      description: n > 0 ? `Adjusted ${n} edge(s) touching this cluster.` : "No cluster↔cluster edges needed changes.",
    });
  },

  reanchorAllClusterToClusterEdges: () => {
    const state = get();
    const next = reanchorAllClusterPairEdges(state.nodes, state.edges);
    const n = next.reduce((acc, e, i) => {
      const o = state.edges[i];
      if (e.sourceHandle !== o.sourceHandle || e.targetHandle !== o.targetHandle) return acc + 1;
      return acc;
    }, 0);
    set({ edges: next, isDirty: true });
    toast.success("All cluster anchors recalculated", {
      description: n > 0 ? `Updated ${n} cluster↔cluster edge(s).` : "No cluster↔cluster edges needed changes.",
    });
  },

  repairClusterEdgeHandles: () => {
    const state = get();
    const next = state.edges.map((e) => {
      const ct = (e.data as { connectionType?: string } | undefined)?.connectionType;
      if (!ct || !CLUSTER_EDGE_TYPES.has(ct)) return e;
      const h = sanitizeClusterEdgeHandlesForReactFlow(
        ct,
        { source: e.source, target: e.target },
        state.nodes,
        { sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined }
      );
      if (e.sourceHandle === h.sourceHandle && e.targetHandle === h.targetHandle) return e;
      return { ...e, sourceHandle: h.sourceHandle, targetHandle: h.targetHandle };
    });
    let changed = false;
    for (let i = 0; i < next.length; i++) {
      const o = state.edges[i];
      const n = next[i];
      if (o.sourceHandle !== n.sourceHandle || o.targetHandle !== n.targetHandle) {
        changed = true;
        break;
      }
    }
    if (changed) {
      set({ edges: next, isDirty: true });
    }
    return changed;
  },

  removeDiagramEdgesByIds: (ids) => {
    if (ids.length === 0) return 0;
    const state = get();
    const drop = new Set(ids);
    const next = state.edges.filter((e) => !drop.has(e.id));
    const removed = state.edges.length - next.length;
    if (removed > 0) set({ edges: next, isDirty: true });
    return removed;
  },

  pruneInvalidDiagramEdges: () => {
    const state = get();
    const invalid = findInvalidDiagramEdges(state.nodes, state.edges);
    if (invalid.length === 0) return 0;
    const drop = new Set(invalid.map((i) => i.edgeId));
    const next = state.edges.filter((e) => !drop.has(e.id));
    set({ edges: next, isDirty: true });
    return invalid.length;
  },

  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),

  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),

  onConnect: (connection) => {
    const state = get();
    const sourceNode = state.nodes.find((n) => n.id === connection.source);
    const targetNode = state.nodes.find((n) => n.id === connection.target);

    if (!sourceNode || !targetNode) {
      toast.error("Connection failed", {
        description: !sourceNode
          ? `Source node "${connection.source}" is missing from the diagram.`
          : `Target node "${connection.target}" is missing from the diagram.`,
      });
      return;
    }

    if (connection.source === connection.target) {
      toast.warning("Cannot connect a node to itself", {
        description: "Drag from this cluster to a different cluster to add replication, site replication, or ILM tiering.",
      });
      return;
    }

    // Detect cluster-to-cluster connections — any handle between two cluster nodes
    const isClusterToCluster = sourceNode.type === "cluster" && targetNode.type === "cluster";

    if (isClusterToCluster) {
      // Cluster-to-cluster: offer cluster-level connection types
      const clusterTypes = ["cluster-replication", "cluster-site-replication", "cluster-tiering"];
      const sourceNodePos = sourceNode.position;
      const targetNodePos = targetNode.position;
      const sourceLabel = String((sourceNode.data as { label?: string }).label || connection.source).trim();
      const targetLabel = String((targetNode.data as { label?: string }).label || connection.target).trim();
      set({
        pendingConnection: {
          connection,
          validTypes: clusterTypes,
          sourcePos: sourceNodePos,
          targetPos: targetNodePos,
          clusterFlowLabels: { sourceLabel, targetLabel },
          allowSwapDirection: true,
        },
      });
      return;
    }

    // nginx → cluster or cluster → nginx: always use nginx-backend
    const isNginxSource = (sourceNode.data as any)?.componentId === "nginx";
    const isNginxTarget = (targetNode.data as any)?.componentId === "nginx";
    if (isNginxSource || isNginxTarget) {
      set({
        edges: addEdge(
          {
            ...connection,
            type: "animated",
            data: {
              connectionType: "nginx-backend",
              network: "default",
              label: defaultEdgeLabelForTarget(connection.target, state.nodes),
              status: "idle",
            },
          },
          state.edges
        ),
      });
      return;
    }

    const sourceComponentId = (sourceNode.data as any)?.componentId;
    const targetComponentId = (targetNode.data as any)?.componentId;

    // MinIO (cluster or standalone) ↔ S3 File Browser — always plain `s3`.
    // Handled before Trino / Spark / generator paths so it never depends on AIStor Tables, MCP, or edition.
    const isS3FileBrowser = (cid: string | undefined) => cid === "s3-file-browser";
    const isMinioS3Peer = (n: (typeof state.nodes)[0]) =>
      n.type === "cluster" || (n.data as { componentId?: string } | undefined)?.componentId === "minio";

    if (
      (isMinioS3Peer(sourceNode) && isS3FileBrowser(targetComponentId)) ||
      (isS3FileBrowser(sourceComponentId) && isMinioS3Peer(targetNode))
    ) {
      const minioFirst = isMinioS3Peer(sourceNode) && isS3FileBrowser(targetComponentId);
      const browserNode = minioFirst ? targetNode : sourceNode;
      const conn = minioFirst
        ? connection
        : {
            ...connection,
            source: connection.target,
            target: connection.source,
            sourceHandle: connection.targetHandle,
            targetHandle: connection.sourceHandle,
          };
      set({
        edges: addEdge(
          {
            ...conn,
            type: "animated",
            data: {
              connectionType: "s3",
              network: "default",
              label: defaultEdgeLabelForTarget(browserNode.id, state.nodes),
              status: "idle",
            },
          },
          state.edges
        ),
      });
      return;
    }

    // Cluster → Trino: require aistor_tables_enabled
    if (sourceNode.type === "cluster" && (targetNode.data as any)?.componentId === "trino") {
      const aistorEnabled = (sourceNode.data as any)?.aistorTablesEnabled === true;
      if (!aistorEnabled) {
        toast.warning("Enable AIStor Tables on this cluster to connect to Trino directly", {
          description: "Toggle 'Enable AIStor Tables' in the cluster properties panel first.",
        });
        return;
      }
      // Add aistor-tables edge directly
      set({
        edges: addEdge(
          {
            ...connection,
            type: "animated",
            data: {
              connectionType: "aistor-tables",
              network: "default",
              label: defaultEdgeLabelForTarget(connection.target, state.nodes),
              status: "idle",
            },
          },
          state.edges
        ),
      });
      return;
    }

    // --- External System / Data Generator → MinIO Node or Cluster ---
    const SOURCE_ES_DG = ["external-system", "data-generator"];
    if (
      SOURCE_ES_DG.includes(sourceComponentId || "") &&
      (targetNode.type === "cluster" || targetComponentId === "minio")
    ) {
      const aistorEnabled = (targetNode.data as any).aistorTablesEnabled === true;

      // External System → MinIO: integration follows Data sink (ES_SINK_MODE), not a connection-type picker.
      if (sourceComponentId === "external-system") {
        const sinkMode = (sourceNode.data as { config?: Record<string, string> } | undefined)?.config?.ES_SINK_MODE;
        const filesOnly = sinkMode === "files_only";
        const connType =
          filesOnly || !aistorEnabled ? "s3" : "aistor-tables";
        set({
          edges: addEdge(
            {
              ...connection,
              type: "animated",
              data: {
                connectionType: connType,
                network: "default",
                label: defaultEdgeLabelForTarget(connection.target, state.nodes),
                status: "idle",
              },
            },
            state.edges
          ),
        });
        return;
      }

      // data-generator: offer S3 vs AIStor Tables when the target supports Tables
      if (aistorEnabled) {
        set({
          pendingConnection: {
            connection,
            validTypes: ["s3", "aistor-tables"],
            directedOptions: [
              { type: "s3", direction: "forward", label: "S3 → MinIO" },
              { type: "aistor-tables", direction: "forward", label: "AIStor Tables (Iceberg)" },
            ],
            sourcePos: sourceNode.position,
            targetPos: targetNode.position,
          },
        });
      } else {
        // Auto-complete with s3 — add edge directly without showing picker
        set({
          edges: addEdge(
            {
              ...connection,
              type: "animated",
              data: {
                connectionType: "s3",
                network: "default",
                label: defaultEdgeLabelForTarget(connection.target, state.nodes),
                status: "idle",
              },
            },
            state.edges
          ),
        });
      }
      return;
    }

    // MinIO / MinIO cluster ↔ Apache Spark Job (Raw → Iceberg requires AIStor Tables on the MinIO side)
    const isMinioPeerNode = (n: (typeof state.nodes)[0] | undefined) =>
      !!n && (n.type === "cluster" || (n.data as any)?.componentId === "minio");
    const minioPeerHasTables = (n: (typeof state.nodes)[0] | undefined) =>
      (n?.data as any)?.aistorTablesEnabled === true;
    const sparkJobId = "spark-etl-job";
    const towardSparkJob =
      targetComponentId === sparkJobId && isMinioPeerNode(sourceNode);
    const fromSparkJob =
      sourceComponentId === sparkJobId && isMinioPeerNode(targetNode);
    if (towardSparkJob || fromSparkJob) {
      const minioSide = towardSparkJob ? sourceNode : targetNode;
      if (!minioPeerHasTables(minioSide)) {
        toast.warning("Enable AIStor Tables on this MinIO node or cluster to connect the Apache Spark job", {
          description: "Raw → Iceberg is only wired when AIStor Tables is enabled in MinIO or cluster properties.",
        });
        return;
      }
      set({
        pendingConnection: {
          connection,
          validTypes: ["s3", "aistor-tables"],
          directedOptions: [
            { type: "s3", direction: "forward", label: "S3 (raw + warehouse buckets)" },
            { type: "aistor-tables", direction: "forward", label: "AIStor Tables (Iceberg catalog path)" },
          ],
          sourcePos: sourceNode.position,
          targetPos: targetNode.position,
        },
      });
      return;
    }

    // If no manifest data available, fall back to "data" type
    const sourceConnections = sourceComponentId ? state.componentManifests[sourceComponentId] : null;
    const targetConnections = targetComponentId ? state.componentManifests[targetComponentId] : null;

    if (!sourceConnections || !targetConnections) {
      set({
        edges: addEdge(
          {
            ...connection,
            type: "animated",
            data: {
              connectionType: "data",
              network: "default",
              label: defaultEdgeLabelForTarget(connection.target, state.nodes),
              status: "idle",
            },
          },
          state.edges
        ),
      });
      return;
    }

    const srcProvides = sourceConnections.provides.map((p) => p.type);
    const tgtAccepts = targetConnections.accepts.map((a) => a.type);
    const forwardTypes = srcProvides.filter((t) => tgtAccepts.includes(t));

    // Also check reverse: target provides → source accepts
    const tgtProvides = targetConnections.provides.map((p) => p.type);
    const srcAccepts = sourceConnections.accepts.map((a) => a.type);
    const reverseTypes = tgtProvides.filter((t) => srcAccepts.includes(t));

    if (forwardTypes.length === 0 && reverseTypes.length === 0) {
      toast.warning("Invalid connection", {
        description: `No compatible connection types between ${sourceNode.data.label} and ${targetNode.data.label}.`,
      });
      return;
    }

    const allOptions: DirectedOption[] = [];

    const srcName = (sourceNode.data as any)?.displayName || sourceNode.id;
    const tgtName = (targetNode.data as any)?.displayName || targetNode.id;

    for (const t of forwardTypes) {
      allOptions.push({ type: t, direction: "forward", label: `${srcName} → ${tgtName}` });
    }
    for (const t of reverseTypes) {
      allOptions.push({ type: t, direction: "reverse", label: `${tgtName} → ${srcName}` });
    }

    // Single option with clear direction — apply directly
    if (allOptions.length === 1) {
      const opt = allOptions[0];
      const conn = opt.direction === "forward" ? connection : {
        ...connection,
        source: connection.target,
        target: connection.source,
        sourceHandle: connection.targetHandle,
        targetHandle: connection.sourceHandle,
      };
      set({
        edges: addEdge(
          {
            ...conn,
            type: "animated",
            data: {
              connectionType: opt.type,
              network: "default",
              label: defaultEdgeLabelForTarget(conn.target, state.nodes),
              status: "idle",
            },
          },
          state.edges
        ),
      });
      return;
    }

    // Multiple options — show picker with direction labels
    const sourceNodePos = sourceNode.position;
    const targetNodePos = targetNode.position;
    set({
      pendingConnection: {
        connection,
        validTypes: allOptions.map((o) => o.type),
        directedOptions: allOptions,
        sourcePos: sourceNodePos,
        targetPos: targetNodePos,
      },
    });
  },

  addNode: (node) => {
    const current = get().nodes;
    // Group nodes must render below all other nodes — prepend so React Flow draws them first
    const next = node.type === "group" ? [node, ...current] : [...current, node];
    set({ nodes: next });
  },

  setSelectedNode: (id) => {
    const state = get();
    const node = id ? state.nodes.find((n) => n.id === id) : null;
    const isCluster = node?.type === "cluster";
    set({
      selectedNodeId: id,
      selectedEdgeId: null,
      selectedClusterElement: isCluster ? { type: "cluster" } : null,
    });
  },

  setSelectedEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null, selectedClusterElement: null }),

  setSelectedClusterElement: (el) => set({ selectedClusterElement: el }),

  setNodes: (nodes) => {
    // Ensure group nodes stay first in the array so React Flow renders them below all others
    const sorted = [...nodes.filter((n) => n.type === "group"), ...nodes.filter((n) => n.type !== "group")];
    set({ nodes: sorted });
  },
  setEdges: (edges) => set({ edges }),

  updateNodeHealth: (nodeId, health) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, health } } : n
      ),
    }),

  setComponentManifests: (manifests) => set({ componentManifests: manifests }),

  isDirty: false,
  setDirty: (dirty) => set({ isDirty: dirty }),

  clipboard: null,
  setClipboard: (node) => set({ clipboard: node }),

  designerWebUiOverlay: null,
  setDesignerWebUiOverlay: (o) => set({ designerWebUiOverlay: o }),

  setPendingConnection: (pending) => set({ pendingConnection: pending }),

  swapPendingConnectionDirection: () => {
    const state = get();
    const p = state.pendingConnection;
    if (!p?.allowSwapDirection) return;
    const c = p.connection;
    // Do not swap handle ids onto the other node: a target handle (e.g. cluster-in-top) must not
    // become sourceHandle after swap — React Flow / addEdge reject invalid handle roles. Clear
    // handles so completePendingConnection picks canonical handles for the new source→target.
    set({
      pendingConnection: {
        ...p,
        connection: {
          ...c,
          source: c.target,
          target: c.source,
          sourceHandle: null,
          targetHandle: null,
        },
        sourcePos: p.targetPos,
        targetPos: p.sourcePos,
        clusterFlowLabels:
          p.clusterFlowLabels != null
            ? {
                sourceLabel: p.clusterFlowLabels.targetLabel,
                targetLabel: p.clusterFlowLabels.sourceLabel,
              }
            : undefined,
      },
    });
  },

  completePendingConnection: (connectionType: string, direction?: "forward" | "reverse") => {
    const state = get();
    const pending = state.pendingConnection;
    if (!pending) {
      toast.error("Nothing to connect", {
        description: "The connection dialog expired or was cleared. Drag from one cluster handle to another again, then pick a connection type.",
      });
      return;
    }

    // Determine actual direction from directedOptions if available
    let actualDirection = direction;
    if (!actualDirection && pending.directedOptions) {
      const match = pending.directedOptions.find((o) => o.type === connectionType);
      actualDirection = match?.direction ?? "forward";
    }

    // Swap source/target if reverse direction
    const conn = actualDirection === "reverse" ? {
      source: pending.connection.target,
      target: pending.connection.source,
      sourceHandle: pending.connection.targetHandle ?? null,
      targetHandle: pending.connection.sourceHandle ?? null,
    } : {
      source: pending.connection.source,
      target: pending.connection.target,
      sourceHandle: pending.connection.sourceHandle ?? null,
      targetHandle: pending.connection.targetHandle ?? null,
    };

    // Cluster↔cluster: keep the exact handles the user dragged (e.g. bottom → top). Canonical
    // geometry is only for re-anchor actions and legacy edges missing handles.
    const handlesRaw =
      CLUSTER_EDGE_TYPES.has(connectionType) && conn.sourceHandle && conn.targetHandle
        ? { sourceHandle: conn.sourceHandle, targetHandle: conn.targetHandle }
        : canonicalHandlesForClusterEdge(connectionType, conn, state.nodes);
    const handles = sanitizeClusterEdgeHandlesForReactFlow(
      connectionType,
      { source: conn.source, target: conn.target },
      state.nodes,
      handlesRaw
    );

    const srcNode = state.nodes.find((n) => n.id === conn.source);
    const tgtNode = state.nodes.find((n) => n.id === conn.target);
    const srcL = String((srcNode?.data as { label?: string }).label || conn.source).trim();
    const tgtL = String((tgtNode?.data as { label?: string }).label || conn.target).trim();
    const clusterFlowLabel = CLUSTER_EDGE_TYPES.has(connectionType) ? `${srcL} → ${tgtL}` : "";

    // Create edge directly with unique ID (avoids addEdge dedup issues)
    const edgeId = `e-${conn.source}-${conn.target}-${connectionType}-${Date.now()}`;
    const newEdge: Edge = {
      id: edgeId,
      source: conn.source!,
      target: conn.target!,
      sourceHandle: handles.sourceHandle,
      targetHandle: handles.targetHandle,
      type: "animated",
      data: {
        connectionType,
        network: "default",
        label: clusterFlowLabel || defaultEdgeLabelForTarget(conn.target, state.nodes),
        status: "idle",
      },
    };

    try {
      set({
        edges: [...state.edges, newEdge],
        pendingConnection: null,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error("Could not add connection", { description: msg });
    }
  },
}));
