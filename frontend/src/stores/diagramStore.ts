import { create } from "zustand";
import { Node, Edge, OnNodesChange, OnEdgesChange, applyNodeChanges, applyEdgeChanges, Connection, addEdge } from "@xyflow/react";
import { toast } from "sonner";
import type { ComponentSummary, ConnectionsDef } from "../types";

export interface PendingConnection {
  connection: Connection;
  validTypes: string[];
  sourcePos: { x: number; y: number };
  targetPos: { x: number; y: number };
}

interface DiagramState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  componentManifests: Record<string, ConnectionsDef>;
  pendingConnection: PendingConnection | null;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  addNode: (node: Node) => void;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  updateNodeHealth: (nodeId: string, health: string) => void;
  setComponentManifests: (manifests: Record<string, ConnectionsDef>) => void;
  setPendingConnection: (pending: PendingConnection | null) => void;
  completePendingConnection: (connectionType: string) => void;
}

export const useDiagramStore = create<DiagramState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  selectedEdgeId: null,
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

    const providesTypes = sourceConnections.provides.map((p) => p.type);
    const acceptsTypes = targetConnections.accepts.map((a) => a.type);
    const validTypes = providesTypes.filter((t) => acceptsTypes.includes(t));

    if (validTypes.length === 0) {
      toast.warning("Invalid connection", {
        description: `${sourceNode.data.label} does not provide any type that ${targetNode.data.label} accepts.`,
      });
      return;
    }

    if (validTypes.length === 1) {
      set({
        edges: addEdge(
          { ...connection, type: "animated", data: { connectionType: validTypes[0], network: "default", label: "", status: "idle" } },
          state.edges
        ),
      });
      return;
    }

    // Multiple valid types — show picker
    const sourceNodePos = sourceNode.position;
    const targetNodePos = targetNode.position;
    set({
      pendingConnection: {
        connection,
        validTypes,
        sourcePos: sourceNodePos,
        targetPos: targetNodePos,
      },
    });
  },

  addNode: (node) => set({ nodes: [...get().nodes, node] }),

  setSelectedNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),

  setSelectedEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  updateNodeHealth: (nodeId, health) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, health } } : n
      ),
    }),

  setComponentManifests: (manifests) => set({ componentManifests: manifests }),

  setPendingConnection: (pending) => set({ pendingConnection: pending }),

  completePendingConnection: (connectionType: string) => {
    const state = get();
    const pending = state.pendingConnection;
    if (!pending) return;
    set({
      edges: addEdge(
        { ...pending.connection, type: "animated", data: { connectionType, network: "default", label: "", status: "idle" } },
        state.edges
      ),
      pendingConnection: null,
    });
  },
}));
