import type { Connection, Edge, Node } from "@xyflow/react";

export const CLUSTER_EDGE_TYPES = new Set([
  "cluster-replication",
  "cluster-site-replication",
  "cluster-tiering",
]);

/** Handle ids that are `type="source"` on ClusterNode. */
export const CLUSTER_SOURCE_HANDLE_IDS = new Set([
  "data-out",
  "cluster-out-bottom",
  "cluster-out",
  "cluster-out-left",
]);

/** Handle ids that are `type="target"` on ClusterNode. */
export const CLUSTER_TARGET_HANDLE_IDS = new Set([
  "data-in",
  "cluster-in-top",
  "cluster-in",
  "cluster-in-right",
]);

/**
 * React Flow requires source handles to exist as `type="source"` on the source node, and targets
 * as `type="target"` on the target. Legacy YAML or cross-type edges can store target ids on the
 * source side (e.g. `cluster-in`); normalize before addEdge / hydrate.
 */
export function sanitizeClusterEdgeHandlesForReactFlow(
  connectionType: string,
  conn: { source: string; target: string },
  nodes: Node[],
  handles: { sourceHandle?: string; targetHandle?: string },
): { sourceHandle?: string; targetHandle?: string } {
  const src = nodes.find((n) => n.id === conn.source);
  const tgt = nodes.find((n) => n.id === conn.target);
  const involvesCluster = src?.type === "cluster" || tgt?.type === "cluster";
  if (!involvesCluster) return handles;

  let sourceHandle = handles.sourceHandle;
  let targetHandle = handles.targetHandle;
  const bothCluster = src?.type === "cluster" && tgt?.type === "cluster";

  const canon = () =>
    canonicalHandlesForClusterEdge(
      connectionType,
      { source: conn.source, target: conn.target, sourceHandle: null, targetHandle: null },
      nodes,
    );

  if (CLUSTER_EDGE_TYPES.has(connectionType) && bothCluster) {
    if (src?.type === "cluster") {
      if (!sourceHandle || !CLUSTER_SOURCE_HANDLE_IDS.has(sourceHandle)) {
        sourceHandle = canon().sourceHandle;
      }
    }
    if (tgt?.type === "cluster") {
      if (!targetHandle || !CLUSTER_TARGET_HANDLE_IDS.has(targetHandle)) {
        targetHandle = canon().targetHandle;
      }
    }
    return { sourceHandle, targetHandle };
  }

  if (src?.type === "cluster") {
    if (!sourceHandle || CLUSTER_TARGET_HANDLE_IDS.has(sourceHandle) || !CLUSTER_SOURCE_HANDLE_IDS.has(sourceHandle)) {
      sourceHandle = "data-out";
    }
  }
  if (tgt?.type === "cluster") {
    if (!targetHandle || CLUSTER_SOURCE_HANDLE_IDS.has(targetHandle) || !CLUSTER_TARGET_HANDLE_IDS.has(targetHandle)) {
      targetHandle = "data-in";
    }
  }

  if (src?.type === "cluster" && tgt?.type === "component") {
    const cid = (tgt.data as { componentId?: string })?.componentId;
    if (
      targetHandle &&
      (CLUSTER_TARGET_HANDLE_IDS.has(targetHandle) || CLUSTER_SOURCE_HANDLE_IDS.has(targetHandle))
    ) {
      targetHandle = cid === "minio" ? "bottom-in" : undefined;
    }
  }
  if (src?.type === "component" && tgt?.type === "cluster") {
    const cid = (src.data as { componentId?: string })?.componentId;
    if (
      sourceHandle &&
      (CLUSTER_TARGET_HANDLE_IDS.has(sourceHandle) || CLUSTER_SOURCE_HANDLE_IDS.has(sourceHandle))
    ) {
      sourceHandle = undefined;
      if (cid === "minio") {
        sourceHandle = "bottom-out";
      }
    }
    if (!sourceHandle || CLUSTER_TARGET_HANDLE_IDS.has(sourceHandle)) {
      sourceHandle = undefined;
    }
  }

  return { sourceHandle, targetHandle };
}

/**
 * When a wire starts on a cluster target handle (e.g. data-in) but React Flow marks the cluster
 * as source, swap endpoints so handles match source/target roles.
 */
export function normalizeClusterComponentConnection(
  connection: Connection,
  nodes: Node[],
): Connection {
  const src = nodes.find((n) => n.id === connection.source);
  const tgt = nodes.find((n) => n.id === connection.target);
  if (!src || !tgt) return connection;

  const sourceHandle = connection.sourceHandle ?? null;
  const targetHandle = connection.targetHandle ?? null;

  if (
    src.type === "cluster" &&
    sourceHandle &&
    CLUSTER_TARGET_HANDLE_IDS.has(sourceHandle) &&
    tgt.type === "component"
  ) {
    return {
      ...connection,
      source: connection.target,
      target: connection.source,
      sourceHandle: targetHandle,
      targetHandle: sourceHandle,
    };
  }

  if (
    tgt.type === "cluster" &&
    targetHandle &&
    CLUSTER_SOURCE_HANDLE_IDS.has(targetHandle) &&
    src.type === "component"
  ) {
    return {
      ...connection,
      source: connection.target,
      target: connection.source,
      sourceHandle: targetHandle,
      targetHandle: sourceHandle,
    };
  }

  return connection;
}

/** Normalize cluster↔component polarity, then assign valid handle ids for React Flow. */
export function prepareConnectionForReactFlow(
  connection: Connection,
  nodes: Node[],
  connectionType: string,
): Connection {
  const norm = normalizeClusterComponentConnection(connection, nodes);
  const h = sanitizeClusterEdgeHandlesForReactFlow(
    connectionType,
    { source: norm.source!, target: norm.target! },
    nodes,
    {
      sourceHandle: norm.sourceHandle ?? undefined,
      targetHandle: norm.targetHandle ?? undefined,
    },
  );
  return {
    ...norm,
    sourceHandle: h.sourceHandle ?? null,
    targetHandle: h.targetHandle ?? null,
  };
}

/**
 * Infer handles from cluster layout (used when handles are missing, on load, and when the user
 * runs "Reset connection anchors"). New drags preserve the user's handles in the store instead.
 */
export function canonicalHandlesForClusterEdge(
  connectionType: string,
  edge: { source: string; target: string; sourceHandle: string | null; targetHandle: string | null },
  nodes: Node[]
): { sourceHandle: string | undefined; targetHandle: string | undefined } {
  if (!CLUSTER_EDGE_TYPES.has(connectionType)) {
    return { sourceHandle: edge.sourceHandle ?? undefined, targetHandle: edge.targetHandle ?? undefined };
  }
  const src = nodes.find((n) => n.id === edge.source);
  const tgt = nodes.find((n) => n.id === edge.target);
  if (!src || !tgt || src.type !== "cluster" || tgt.type !== "cluster") {
    return { sourceHandle: edge.sourceHandle ?? undefined, targetHandle: edge.targetHandle ?? undefined };
  }
  const dx = tgt.position.x - src.position.x;
  const dy = tgt.position.y - src.position.y;
  const adx = Math.abs(dx);
  const ady = Math.abs(dy);

  if (ady > adx && ady > 40) {
    return { sourceHandle: "cluster-out-bottom", targetHandle: "cluster-in-top" };
  }
  if (adx > ady && dx > 40) {
    return { sourceHandle: "data-out", targetHandle: "data-in" };
  }
  if (adx > ady && dx < -40) {
    return { sourceHandle: "cluster-out-left", targetHandle: "cluster-in-right" };
  }
  if (ady >= adx && ady > 20) {
    return { sourceHandle: "cluster-out-bottom", targetHandle: "cluster-in-top" };
  }
  if (dx >= 0) {
    return { sourceHandle: "data-out", targetHandle: "data-in" };
  }
  return { sourceHandle: "cluster-out-left", targetHandle: "cluster-in-right" };
}

export function reanchorClusterEdgesTouching(clusterId: string, nodes: Node[], edges: Edge[]): Edge[] {
  return edges.map((e) => {
    const ctype = (e.data as { connectionType?: string } | undefined)?.connectionType;
    if (!ctype || !CLUSTER_EDGE_TYPES.has(ctype)) return e;
    if (e.source !== clusterId && e.target !== clusterId) return e;
    const srcN = nodes.find((n) => n.id === e.source);
    const tgtN = nodes.find((n) => n.id === e.target);
    if (srcN?.type === "cluster" && tgtN?.type === "cluster") {
      const h = canonicalHandlesForClusterEdge(ctype, {
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? null,
        targetHandle: e.targetHandle ?? null,
      }, nodes);
      return { ...e, sourceHandle: h.sourceHandle, targetHandle: h.targetHandle };
    }
    const h = sanitizeClusterEdgeHandlesForReactFlow(
      ctype,
      { source: e.source, target: e.target },
      nodes,
      { sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined }
    );
    return { ...e, sourceHandle: h.sourceHandle, targetHandle: h.targetHandle };
  });
}

export function reanchorAllClusterPairEdges(nodes: Node[], edges: Edge[]): Edge[] {
  return edges.map((e) => {
    const ctype = (e.data as { connectionType?: string } | undefined)?.connectionType;
    if (!ctype || !CLUSTER_EDGE_TYPES.has(ctype)) return e;
    const srcN = nodes.find((n) => n.id === e.source);
    const tgtN = nodes.find((n) => n.id === e.target);
    if (srcN?.type === "cluster" && tgtN?.type === "cluster") {
      const h = canonicalHandlesForClusterEdge(ctype, {
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? null,
        targetHandle: e.targetHandle ?? null,
      }, nodes);
      return { ...e, sourceHandle: h.sourceHandle, targetHandle: h.targetHandle };
    }
    const h = sanitizeClusterEdgeHandlesForReactFlow(
      ctype,
      { source: e.source, target: e.target },
      nodes,
      { sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined }
    );
    return { ...e, sourceHandle: h.sourceHandle, targetHandle: h.targetHandle };
  });
}
