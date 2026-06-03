import type { Edge, Node } from "@xyflow/react";
import {
  CLUSTER_SOURCE_HANDLE_IDS,
  CLUSTER_TARGET_HANDLE_IDS,
} from "./clusterConnectionAnchors";

export interface DiagramEdgeIssue {
  edgeId: string;
  source: string;
  target: string;
  connectionType?: string;
  issues: string[];
  /** True when repairClusterEdgeHandles / prepareConnectionForReactFlow can fix in place. */
  repairable?: boolean;
}

const COMPONENT_SOURCE_HANDLES = new Set<string | undefined>([undefined, "top-out", "bottom-out"]);
const COMPONENT_TARGET_HANDLES = new Set<string | undefined>([undefined, "top", "bottom-in"]);

function clusterHandleIssues(
  edge: Edge,
  src: Node | undefined,
  tgt: Node | undefined,
): string[] {
  const issues: string[] = [];
  const sh = edge.sourceHandle ?? undefined;
  const th = edge.targetHandle ?? undefined;

  if (src?.type === "cluster" && sh && CLUSTER_TARGET_HANDLE_IDS.has(sh)) {
    issues.push(
      `Cluster source uses target handle "${sh}" (React Flow requires a source handle such as data-out)`,
    );
  }
  if (src?.type === "cluster" && sh && !CLUSTER_SOURCE_HANDLE_IDS.has(sh) && !CLUSTER_TARGET_HANDLE_IDS.has(sh)) {
    issues.push(`Unknown cluster source handle "${sh}"`);
  }
  if (tgt?.type === "cluster" && th && CLUSTER_SOURCE_HANDLE_IDS.has(th)) {
    issues.push(
      `Cluster target uses source handle "${th}" (React Flow requires a target handle such as data-in)`,
    );
  }
  if (tgt?.type === "cluster" && th && !CLUSTER_TARGET_HANDLE_IDS.has(th) && !CLUSTER_SOURCE_HANDLE_IDS.has(th)) {
    issues.push(`Unknown cluster target handle "${th}"`);
  }

  if (src?.type === "component" && sh && !COMPONENT_SOURCE_HANDLES.has(sh) && COMPONENT_TARGET_HANDLES.has(sh)) {
    issues.push(`Component source uses target handle "${sh}"`);
  }
  if (tgt?.type === "component" && th && !COMPONENT_TARGET_HANDLES.has(th) && COMPONENT_SOURCE_HANDLES.has(th)) {
    issues.push(`Component target uses source handle "${th}"`);
  }

  return issues;
}

/**
 * Orphaned edges (missing nodes) and invalid handle polarity (common on MinIO cluster links).
 */
export function findInvalidDiagramEdges(
  nodes: Node[],
  edges: Edge[],
): DiagramEdgeIssue[] {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const out: DiagramEdgeIssue[] = [];

  for (const e of edges) {
    const issues: string[] = [];
    const src = e.source ? nodeById.get(e.source) : undefined;
    const tgt = e.target ? nodeById.get(e.target) : undefined;

    if (!e.source) issues.push("Edge has no source id");
    else if (!src) issues.push(`Missing source node "${e.source}"`);
    if (!e.target) issues.push("Edge has no target id");
    else if (!tgt) issues.push(`Missing target node "${e.target}"`);

    if (src && tgt) {
      issues.push(...clusterHandleIssues(e, src, tgt));
    }

    if (issues.length > 0) {
      const data = e.data as { connectionType?: string } | undefined;
      const repairable =
        src != null &&
        tgt != null &&
        issues.every((msg) => !msg.startsWith("Missing "));
      out.push({
        edgeId: e.id,
        source: e.source ?? "",
        target: e.target ?? "",
        connectionType: data?.connectionType,
        issues,
        repairable,
      });
    }
  }

  return out;
}
