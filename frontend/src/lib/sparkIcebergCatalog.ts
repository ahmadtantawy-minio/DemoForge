import type { Edge, Node } from "@xyflow/react";
import { resolveSparkIcebergCatalogFromDiagram } from "./minioIcebergPeer";

/** UI hint: catalog from linked MinIO cluster/node (AISTOR_TABLES_CATALOG_NAME / SigV4 path). */
export function resolveSparkIcebergCatalogName(
  jobNodeId: string,
  jobConfig: Record<string, string> | undefined,
  nodes: Node[],
  edges: Edge[],
): string {
  return resolveSparkIcebergCatalogFromDiagram(jobNodeId, jobConfig, nodes, edges);
}
