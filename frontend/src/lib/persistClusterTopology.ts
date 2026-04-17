import type { Edge, Node } from "@xyflow/react";
import { applyClusterTopology, saveDiagram } from "../api/client";
import { toast } from "./toast";

/** Cluster `data` patches that require compose regen + docker compose up when the demo is running. */
const COMPOSE_AFFECTING_KEYS = new Set([
  "serverPools",
  "config",
  "credentials",
  "mcpEnabled",
  "aistorTablesEnabled",
]);

export function clusterDataPatchAffectsCompose(patch: Record<string, unknown>): boolean {
  return Object.keys(patch).some((k) => COMPOSE_AFFECTING_KEYS.has(k));
}

/** Save diagram YAML then apply compose (running demos). Surfaces toast on success/failure. */
export async function saveDiagramAndApplyClusterTopology(
  activeDemoId: string,
  clusterId: string,
  nodes: Node[],
  edges: Edge[]
): Promise<void> {
  try {
    await saveDiagram(activeDemoId, nodes, edges);
    await applyClusterTopology(activeDemoId, clusterId);
    toast.success("Cluster topology applied to Docker");
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    toast.error(`Topology apply failed: ${msg}`);
    throw e;
  }
}
