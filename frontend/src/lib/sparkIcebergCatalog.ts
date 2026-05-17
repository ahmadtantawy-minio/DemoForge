import type { Edge, Node } from "@xyflow/react";
import { AISTOR_TABLES_DEFAULT_CATALOG_NAME } from "./aistorTablesDefaults";

const RESERVED_CATALOG_IDS = new Set(["iceberg", "hive", "memory", "system"]);

function sanitizeCatalogStem(name: string, fallback: string): string {
  const safe = name.replace(/[^a-zA-Z0-9_-]/g, "_").replace(/^_+|_+$/g, "") || fallback;
  if (RESERVED_CATALOG_IDS.has(safe.toLowerCase())) return fallback;
  return safe;
}

type PeerConfig = Record<string, string> | undefined;

function catalogFromPeerConfig(pc: PeerConfig, tablesEnabled: boolean): string | null {
  if (!pc) return null;
  const spark = (pc.ICEBERG_SPARK_CATALOG_NAME || "").trim();
  if (spark) return spark;
  const aistor = (pc.AISTOR_TABLES_CATALOG_NAME || "").trim();
  if (aistor) return sanitizeCatalogStem(aistor, AISTOR_TABLES_DEFAULT_CATALOG_NAME);
  if (tablesEnabled) return AISTOR_TABLES_DEFAULT_CATALOG_NAME;
  return null;
}

/** UI hint: same precedence as compose ``_spark_etl_job_spark_catalog_name_from_peer``. */
export function resolveSparkIcebergCatalogName(
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

    const peerId = e.source === jobNodeId ? e.target : e.source;
    const peer = nodes.find((n) => n.id === peerId);
    if (!peer) continue;

    const d = peer.data as {
      componentId?: string;
      config?: Record<string, string>;
      aistorTablesEnabled?: boolean;
    };
    const fromPeer = catalogFromPeerConfig(d.config, d.aistorTablesEnabled === true);
    if (fromPeer) return fromPeer;
  }

  return "iceberg";
}
