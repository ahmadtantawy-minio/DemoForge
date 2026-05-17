import type { Edge, Node } from "@xyflow/react";
import {
  ICEBERG_BROWSER_ID,
  SPARK_ETL_JOB_ID,
  inferIcebergBrowserMinioConnectionType,
  inferSparkEtlMinioConnectionType,
  isMinioDiagramPeer,
} from "./minioIcebergPeer";

/** Upgrade legacy s3/iceberg-catalog edges to aistor-tables where compose expects Tables. */
export function normalizeMinioIcebergEdges(nodes: Node[], edges: Edge[]): Edge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  let changed = false;

  const next = edges.map((edge) => {
    const src = byId.get(edge.source);
    const tgt = byId.get(edge.target);
    const ed = (edge.data || {}) as { connectionType?: string; label?: string; connectionConfig?: Record<string, unknown> };
    const ct = ed.connectionType || "";

    // MinIO ↔ Iceberg Browser
    if (
      (isMinioDiagramPeer(src) && (tgt?.data as { componentId?: string })?.componentId === ICEBERG_BROWSER_ID) ||
      (isMinioDiagramPeer(tgt) && (src?.data as { componentId?: string })?.componentId === ICEBERG_BROWSER_ID)
    ) {
      const minioPeer = isMinioDiagramPeer(src) ? src : tgt;
      const want = inferIcebergBrowserMinioConnectionType(minioPeer);
      if (want && ct !== want && (ct === "s3" || ct === "iceberg-catalog" || ct === "aistor-tables")) {
        changed = true;
        return {
          ...edge,
          data: {
            ...ed,
            connectionType: want,
            label: ed.label || "iceberg v4",
          },
        };
      }
    }

    // MinIO ↔ Spark ETL job
    if (
      (isMinioDiagramPeer(src) && (tgt?.data as { componentId?: string })?.componentId === SPARK_ETL_JOB_ID) ||
      (isMinioDiagramPeer(tgt) && (src?.data as { componentId?: string })?.componentId === SPARK_ETL_JOB_ID)
    ) {
      const minioPeer = isMinioDiagramPeer(src) ? src : tgt;
      const sparkNode = (tgt?.data as { componentId?: string })?.componentId === SPARK_ETL_JOB_ID ? tgt : src;
      const want = inferSparkEtlMinioConnectionType(minioPeer, sparkNode);
      if (want && ct !== want && (ct === "s3" || ct === "aistor-tables")) {
        changed = true;
        return { ...edge, data: { ...ed, connectionType: want } };
      }
    }

    return edge;
  });

  return changed ? next : edges;
}
