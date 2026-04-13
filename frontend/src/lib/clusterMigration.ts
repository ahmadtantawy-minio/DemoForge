import type { MinioServerPool, ClusterNodeData } from "../types";

export function migrateClusterData(data: any): ClusterNodeData {
  if (Array.isArray(data.serverPools) && data.serverPools.length > 0) return data as ClusterNodeData;
  const pool: MinioServerPool = {
    id: "pool-1",
    nodeCount: data.nodeCount ?? 4,
    drivesPerNode: data.drivesPerNode ?? 4,
    diskSizeTb: data.diskSizeTb ?? 1,
    diskType: "ssd",
    ecParity: data.ecParity ?? 3,
    ecParityUpgradePolicy: data.ecParityUpgradePolicy ?? "upgrade",
    volumePath: "/data",
  };
  const { nodeCount, drivesPerNode, diskSizeTb, ecParity, ecParityUpgradePolicy, ...rest } = data;
  return { ...rest, serverPools: [pool] } as ClusterNodeData;
}
