import type { MinioServerPool, ClusterNodeData } from "../types";

export function migrateClusterData(data: any): ClusterNodeData {
  if (Array.isArray(data.serverPools) && data.serverPools.length > 0) return data as ClusterNodeData;
  // Old pre-pool configs had top-level nodeCount/drivesPerNode but those values
  // are unreliable legacy noise. Always use canonical defaults for migrated pools.
  const pool: MinioServerPool = {
    id: "pool-1",
    nodeCount: 4,
    drivesPerNode: 2,
    diskSizeTb: 1,
    diskType: "ssd",
    ecParity: 3,
    ecParityUpgradePolicy: "upgrade",
    volumePath: "/data",
  };
  const { nodeCount, drivesPerNode, diskSizeTb, ecParity, ecParityUpgradePolicy, ...rest } = data;
  return { ...rest, serverPools: [pool] } as ClusterNodeData;
}
