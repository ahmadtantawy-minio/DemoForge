import type { Edge, Node } from "@xyflow/react";

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
  handles: { sourceHandle?: string; targetHandle?: string }
): { sourceHandle?: string; targetHandle?: string } {
  if (!CLUSTER_EDGE_TYPES.has(connectionType)) return handles;
  const src = nodes.find((n) => n.id === conn.source);
  const tgt = nodes.find((n) => n.id === conn.target);
  let sourceHandle = handles.sourceHandle;
  let targetHandle = handles.targetHandle;
  const bothCluster = src?.type === "cluster" && tgt?.type === "cluster";

  const canon = () =>
    canonicalHandlesForClusterEdge(
      connectionType,
      { source: conn.source, target: conn.target, sourceHandle: null, targetHandle: null },
      nodes
    );

  if (src?.type === "cluster") {
    if (!sourceHandle || !CLUSTER_SOURCE_HANDLE_IDS.has(sourceHandle)) {
      const c = canon();
      sourceHandle = bothCluster ? c.sourceHandle : "data-out";
    }
  }
  if (tgt?.type === "cluster") {
    if (!targetHandle || !CLUSTER_TARGET_HANDLE_IDS.has(targetHandle)) {
      const c = canon();
      targetHandle = bothCluster ? c.targetHandle : "data-in";
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
      sourceHandle = cid === "minio" ? "bottom-out" : undefined;
    }
  }

  return { sourceHandle, targetHandle };
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
