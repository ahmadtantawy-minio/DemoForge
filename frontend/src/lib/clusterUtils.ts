import type { MinioServerPool, ContainerInstance } from "../types";
import { computePoolErasureStats } from "./erasure";

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

export function computeClusterAggregates(pools: MinioServerPool[]) {
  const stats = pools.map(p => computePoolErasureStats(p.nodeCount, p.drivesPerNode, p.ecParity, p.diskSizeTb));
  const ecValues = new Set(pools.map(p => p.ecParity));
  return {
    totalNodes: pools.reduce((s, p) => s + p.nodeCount, 0),
    totalDrives: pools.reduce((s, p) => s + p.nodeCount * p.drivesPerNode, 0),
    totalRawTb: stats.reduce((s, ps) => s + ps.rawTb, 0),
    totalUsableTb: stats.reduce((s, ps) => s + ps.usableTb, 0),
    usableRatio: stats.length > 0 ? stats.reduce((s, ps) => s + ps.usableRatio, 0) / stats.length : 0,
    ecSummary: ecValues.size === 1 ? `EC:${pools[0].ecParity}` : "mixed EC",
    maxDriveTolerance: stats.length > 0 ? Math.min(...stats.map(ps => ps.driveTolerance)) : 0,
  };
}

export function nodeContainerName(clusterId: string, poolIndex: number, nodeIndex: number, _totalPools: number): string {
  // compose_generator always uses pool{n} naming regardless of pool count
  return `${clusterId}-pool${poolIndex}-node-${nodeIndex}`;
}
