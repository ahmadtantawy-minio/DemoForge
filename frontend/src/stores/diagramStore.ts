import { create } from "zustand";
import { Node, Edge, OnNodesChange, OnEdgesChange, applyNodeChanges, applyEdgeChanges, Connection, addEdge } from "@xyflow/react";
import { toast } from "sonner";
import type { ComponentSummary, ConnectionsDef } from "../types";

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
  completePendingConnection: (connectionType: string, direction?: "forward" | "reverse") => void;
  isDirty: boolean;
  setDirty: (dirty: boolean) => void;
}

export const useDiagramStore = create<DiagramState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  selectedEdgeId: null,
  selectedClusterElement: null,
  componentManifests: {},
  pendingConnection: null,

  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),

  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),

  onConnect: (connection) => {
    const state = get();
    const sourceNode = state.nodes.find((n) => n.id === connection.source);
    const targetNode = state.nodes.find((n) => n.id === connection.target);

    if (!sourceNode || !targetNode) return;

    // Detect cluster-to-cluster connections — any handle between two cluster nodes
    const isClusterToCluster = sourceNode.type === "cluster" && targetNode.type === "cluster";

    if (isClusterToCluster) {
      // Cluster-to-cluster: offer cluster-level connection types
      const clusterTypes = ["cluster-replication", "cluster-site-replication", "cluster-tiering"];
      const sourceNodePos = sourceNode.position;
      const targetNodePos = targetNode.position;
      set({
        pendingConnection: {
          connection,
          validTypes: clusterTypes,
          sourcePos: sourceNodePos,
          targetPos: targetNodePos,
        },
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
          { ...connection, type: "animated", data: { connectionType: "aistor-tables", network: "default", label: "", status: "idle" } },
          state.edges
        ),
      });
      return;
    }

    // For cluster nodes, use the underlying componentId for manifest lookup
    const sourceComponentId = (sourceNode.data as any)?.componentId;
    const targetComponentId = (targetNode.data as any)?.componentId;

    // If no manifest data available, fall back to "data" type
    const sourceConnections = sourceComponentId ? state.componentManifests[sourceComponentId] : null;
    const targetConnections = targetComponentId ? state.componentManifests[targetComponentId] : null;

    if (!sourceConnections || !targetConnections) {
      set({
        edges: addEdge(
          { ...connection, type: "animated", data: { connectionType: "data", network: "default", label: "", status: "idle" } },
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
          { ...conn, type: "animated", data: { connectionType: opt.type, network: "default", label: "", status: "idle" } },
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

  addNode: (node) => set({ nodes: [...get().nodes, node] }),

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

  setNodes: (nodes) => set({ nodes }),
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

  setPendingConnection: (pending) => set({ pendingConnection: pending }),

  completePendingConnection: (connectionType: string, direction?: "forward" | "reverse") => {
    const state = get();
    const pending = state.pendingConnection;
    if (!pending) return;

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

    // Create edge directly with unique ID (avoids addEdge dedup issues)
    const edgeId = `e-${conn.source}-${conn.target}-${connectionType}-${Date.now()}`;
    const newEdge: Edge = {
      id: edgeId,
      source: conn.source!,
      target: conn.target!,
      sourceHandle: conn.sourceHandle,
      targetHandle: conn.targetHandle,
      type: "animated",
      data: { connectionType, network: "default", label: "", status: "idle" },
    };

    set({
      edges: [...state.edges, newEdge],
      pendingConnection: null,
    });
  },
}));
