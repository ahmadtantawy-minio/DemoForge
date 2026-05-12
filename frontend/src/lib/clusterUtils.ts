import type { MinioServerPool, ContainerInstance } from "../types";
import {
  effectiveStripeSize,
  computePoolErasureStats,
  clampParityToValidStripe,
  formatMinioEcStripeShort,
  minioDefaultStandardParity,
} from "./erasure";

export function getClusterInstances(instances: ContainerInstance[], clusterId: string): ContainerInstance[] {
  return instances.filter(i =>
    (i.node_id.startsWith(`${clusterId}-node-`) || i.node_id.startsWith(`${clusterId}-pool`))
    && i.node_id !== `${clusterId}-lb`
  );
}

export function getPoolInstances(instances: ContainerInstance[], clusterId: string, poolIndex: number, _totalPools: number): ContainerInstance[] {
  // compose_generator always uses pool{n} naming regardless of pool count
  return instances.filter(i => i.node_id.startsWith(`${clusterId}-pool${poolIndex}-node-`));
}

function _poolEcStripeLabel(p: MinioServerPool): string {
  const td = p.nodeCount * p.drivesPerNode;
  const stripe = effectiveStripeSize(td, p.erasureStripeDrives ?? null);
  const par = clampParityToValidStripe(stripe, p.ecParity ?? minioDefaultStandardParity(stripe));
  return formatMinioEcStripeShort(stripe, par);
}

export function computeClusterAggregates(pools: MinioServerPool[]) {
  const stats = pools.map((p) => {
    const td = p.nodeCount * p.drivesPerNode;
    const stripe = effectiveStripeSize(td, p.erasureStripeDrives ?? null);
    const par = clampParityToValidStripe(stripe, p.ecParity ?? minioDefaultStandardParity(stripe));
    return computePoolErasureStats(p.nodeCount, p.drivesPerNode, par, p.diskSizeTb, p.erasureStripeDrives);
  });
  const stripeKeys = new Set(pools.map(_poolEcStripeLabel));
  return {
    totalNodes: pools.reduce((s, p) => s + p.nodeCount, 0),
    totalDrives: pools.reduce((s, p) => s + p.nodeCount * p.drivesPerNode, 0),
    totalRawTb: stats.reduce((s, ps) => s + ps.rawTb, 0),
    totalUsableTb: stats.reduce((s, ps) => s + ps.usableTb, 0),
    usableRatio: stats.length > 0 ? stats.reduce((s, ps) => s + ps.usableRatio, 0) / stats.length : 0,
    ecSummary: stripeKeys.size === 1 ? (Array.from(stripeKeys)[0] ?? "—") : "mixed EC",
    maxDriveTolerance: stats.length > 0 ? Math.min(...stats.map((ps) => ps.driveTolerance)) : 0,
  };
}

export function nodeContainerName(clusterId: string, poolIndex: number, nodeIndex: number, _totalPools: number): string {
  // compose_generator always uses pool{n} naming regardless of pool count
  return `${clusterId}-pool${poolIndex}-node-${nodeIndex}`;
}
