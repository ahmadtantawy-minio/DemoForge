import type { Edge, Node } from "@xyflow/react";
import type { ClusterNodeData } from "../../types";
import { migrateClusterData } from "../../lib/clusterMigration";
import { iamSimSpecRawHasContent, tryParseIamSimSpec } from "./minioIamSimSpec";

const S3_EDGE_TYPES = new Set(["s3", "load-balance", "structured-data", "file-push", "aistor-tables"]);

function clusterDataFromNode(n: Node): ClusterNodeData | null {
  if (n.type !== "cluster") return null;
  return migrateClusterData(n.data as Record<string, unknown>);
}

/** Raw `MINIO_IAM_SIM_SPEC` JSON from the MinIO peer wired to this S3 File Browser (cluster, LB, pool member, or standalone node). */
export function getS3FileBrowserPeerIamSpecRaw(browserNodeId: string, nodes: Node[], edges: Edge[]): string {
  for (const edge of edges) {
    if (!S3_EDGE_TYPES.has(String((edge.data as { connectionType?: string } | undefined)?.connectionType ?? ""))) {
      continue;
    }
    const peerId =
      edge.target === browserNodeId ? edge.source : edge.source === browserNodeId ? edge.target : null;
    if (!peerId) continue;

    const peer = nodes.find((n) => n.id === peerId);
    if (!peer) continue;

    if (peer.type === "cluster") {
      const d = clusterDataFromNode(peer);
      const raw = String(d?.config?.MINIO_IAM_SIM_SPEC ?? "");
      if (iamSimSpecRawHasContent(raw)) return raw;
      continue;
    }

    const comp = (peer.data as { componentId?: string } | undefined)?.componentId;
    if (comp === "minio") {
      const cfg = (peer.data as { config?: Record<string, string> }).config ?? {};
      const raw = String(cfg.MINIO_IAM_SIM_SPEC ?? "");
      if (iamSimSpecRawHasContent(raw)) return raw;
    }

    if (peerId.endsWith("-lb")) {
      const clusterId = peerId.slice(0, -3);
      const cluster = nodes.find((n) => n.id === clusterId && n.type === "cluster");
      if (cluster) {
        const d = clusterDataFromNode(cluster);
        const raw = String(d?.config?.MINIO_IAM_SIM_SPEC ?? "");
        if (iamSimSpecRawHasContent(raw)) return raw;
      }
    }

    const m = peerId.match(/^(.+)-pool\d+-node-/);
    if (m) {
      const clusterId = m[1];
      const cluster = nodes.find((n) => n.id === clusterId && n.type === "cluster");
      if (cluster) {
        const d = clusterDataFromNode(cluster);
        const raw = String(d?.config?.MINIO_IAM_SIM_SPEC ?? "");
        if (iamSimSpecRawHasContent(raw)) return raw;
      }
    }
  }
  return "";
}

export interface S3SimIdentityOption {
  value: string;
  label: string;
}

/** Explicit opt-in: first user from IAM simulation (compose resolves to that user's keys). */
export const S3_SIMULATED_IDENTITY_FIRST = "__first__";

/**
 * Options for the simulated-identity control.
 * - ``""`` = Root (default when unset — backward compatible).
 * - ``__first__`` = first simulated IAM user (explicit least-privilege).
 */
export function getS3SimulatedIdentityOptions(specRaw: string): S3SimIdentityOption[] {
  const spec = tryParseIamSimSpec(specRaw);
  const users = (spec?.users ?? []).filter((u) => {
    const ak = String(u.access_key ?? "").trim();
    const sk = String(u.secret_key ?? "").trim();
    return ak && sk;
  });
  const root: S3SimIdentityOption = { value: "", label: "Root (MinIO administrator)" };
  if (!users.length) {
    return [root];
  }
  const out: S3SimIdentityOption[] = [
    root,
    { value: S3_SIMULATED_IDENTITY_FIRST, label: "First simulated user (IAM least privilege)" },
  ];
  for (const u of users) {
    const ak = String(u.access_key ?? "").trim();
    const label = (u.label && String(u.label).trim()) || ak;
    out.push({ value: ak, label: `${label} (${ak})` });
  }
  return out;
}

export function peerHasIamSimulation(specRaw: string): boolean {
  return iamSimSpecRawHasContent(specRaw);
}
