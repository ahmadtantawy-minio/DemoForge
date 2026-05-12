import type { Edge, Node } from "@xyflow/react";

export interface DiagramEdgeIssue {
  edgeId: string;
  source: string;
  target: string;
  connectionType?: string;
  issues: string[];
}

/**
 * Edges whose source or target node id is not present in `nodes` (orphaned after
 * template edits, copy/paste bugs, or manual JSON edits).
 */
export function findInvalidDiagramEdges(
  nodes: Node[],
  edges: Edge[],
): DiagramEdgeIssue[] {
  const nodeIds = new Set(nodes.map((n) => n.id));
  const out: DiagramEdgeIssue[] = [];

  for (const e of edges) {
    const issues: string[] = [];
    if (!e.source) issues.push("Edge has no source id");
    else if (!nodeIds.has(e.source))
      issues.push(`Missing source node "${e.source}"`);
    if (!e.target) issues.push("Edge has no target id");
    else if (!nodeIds.has(e.target))
      issues.push(`Missing target node "${e.target}"`);
    if (issues.length > 0) {
      const data = e.data as { connectionType?: string } | undefined;
      out.push({
        edgeId: e.id,
        source: e.source ?? "",
        target: e.target ?? "",
        connectionType: data?.connectionType,
        issues,
      });
    }
  }

  return out;
}
