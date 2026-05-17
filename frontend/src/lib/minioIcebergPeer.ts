import type { Edge, Node } from "@xyflow/react";
import { AISTOR_TABLES_DEFAULT_CATALOG_NAME } from "./aistorTablesDefaults";

const RESERVED_CATALOG_IDS = new Set(["iceberg", "hive", "memory", "system"]);

export const SPARK_ETL_JOB_ID = "spark-etl-job";
export const ICEBERG_BROWSER_ID = "iceberg-browser";
export const TRINO_ID = "trino";

export function isMinioDiagramPeer(node: Node | undefined): boolean {
  if (!node) return false;
  return node.type === "cluster" || (node.data as { componentId?: string } | undefined)?.componentId === "minio";
}

export function minioPeerHasAistorTables(node: Node | undefined): boolean {
  if (!node || !isMinioDiagramPeer(node)) return false;
  return (node.data as { aistorTablesEnabled?: boolean } | undefined)?.aistorTablesEnabled === true;
}

function sanitizeCatalogStem(name: string, fallback: string): string {
  const safe = name.replace(/[^a-zA-Z0-9_-]/g, "_").replace(/^_+|_+$/g, "") || fallback;
  if (RESERVED_CATALOG_IDS.has(safe.toLowerCase())) return fallback;
  return safe;
}

/** Catalog id from MinIO cluster / node config (AISTOR_TABLES_CATALOG_NAME). */
export function catalogFromMinioPeerNode(node: Node | undefined): string | null {
  if (!isMinioDiagramPeer(node)) return null;
  const cfg = (node.data as { config?: Record<string, string> } | undefined)?.config;
  const spark = (cfg?.ICEBERG_SPARK_CATALOG_NAME || "").trim();
  if (spark) return spark;
  const aistor = (cfg?.AISTOR_TABLES_CATALOG_NAME || "").trim();
  if (aistor) return sanitizeCatalogStem(aistor, AISTOR_TABLES_DEFAULT_CATALOG_NAME);
  if (minioPeerHasAistorTables(node)) return AISTOR_TABLES_DEFAULT_CATALOG_NAME;
  return null;
}

export function sparkJobMode(node: Node | undefined): string {
  return String((node.data as { config?: Record<string, string> } | undefined)?.config?.JOB_MODE || "raw_to_iceberg")
    .toLowerCase();
}

export function sparkJobUsesAistorTables(sparkNode: Node | undefined): boolean {
  const mode = sparkJobMode(sparkNode);
  return mode !== "raw_to_parquet";
}

/** Connection type for a new MinIO peer ↔ spark-etl-job edge (no user picker). */
export function inferSparkEtlMinioConnectionType(
  minioPeer: Node | undefined,
  sparkNode: Node | undefined,
): "aistor-tables" | "s3" | null {
  if (!isMinioDiagramPeer(minioPeer) || (sparkNode?.data as { componentId?: string })?.componentId !== SPARK_ETL_JOB_ID) {
    return null;
  }
  if (sparkJobUsesAistorTables(sparkNode)) {
    return minioPeerHasAistorTables(minioPeer) ? "aistor-tables" : null;
  }
  return "s3";
}

/** AIStor Tables is the only MinIO→Iceberg-browser link when Tables are enabled. */
export function inferIcebergBrowserMinioConnectionType(minioPeer: Node | undefined): "aistor-tables" | null {
  if (!isMinioDiagramPeer(minioPeer) || !minioPeerHasAistorTables(minioPeer)) return null;
  return "aistor-tables";
}

export function resolveSparkIcebergCatalogFromDiagram(
  jobNodeId: string,
  jobConfig: Record<string, string> | undefined,
  nodes: Node[],
  edges: Edge[],
): string {
  const jobOverride = (jobConfig?.ICEBERG_SPARK_CATALOG_NAME || "").trim();
  if (jobOverride) return jobOverride;

  for (const e of edges) {
    if (e.source !== jobNodeId && e.target !== jobNodeId) continue;
    const ct = String((e.data as { connectionType?: string } | undefined)?.connectionType || "");
    if (ct !== "s3" && ct !== "aistor-tables") continue;
    const peer = nodes.find((n) => n.id === (e.source === jobNodeId ? e.target : e.source));
    const fromPeer = catalogFromMinioPeerNode(peer);
    if (fromPeer) return fromPeer;
  }

  return AISTOR_TABLES_DEFAULT_CATALOG_NAME;
}
