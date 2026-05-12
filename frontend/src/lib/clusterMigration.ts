import type { MinioServerPool, ClusterNodeData } from "../types";
import {
  effectiveStripeSize,
  canonicalErasureStripeDrivesPref,
  clampParityToValidStripe,
  minioDefaultStandardParity,
} from "./erasure";

/** Clamp pool EC parity and sync legacy top-level `ecParity` to pool 1 (matches backend normalize). */
export function normalizeClusterPoolsEc(data: ClusterNodeData): ClusterNodeData {
  const pools = data.serverPools;
  if (!pools?.length) return data;
  const nextPools = pools.map((p) => {
    const nc = p.nodeCount ?? 1;
    const dp = p.drivesPerNode ?? 1;
    const td = nc * dp;
    const stripePref = canonicalErasureStripeDrivesPref(td, p.erasureStripeDrives);
    const stripe = effectiveStripeSize(td, stripePref);
    const clamped = clampParityToValidStripe(
      stripe,
      p.ecParity ?? minioDefaultStandardParity(stripe),
    );
    const rawStripe = p.erasureStripeDrives ?? null;
    if (stripePref !== rawStripe) {
      if (stripePref == null) {
        const { erasureStripeDrives: _drop, ...rest } = p;
        return { ...rest, ecParity: clamped } as MinioServerPool;
      }
      return { ...p, ecParity: clamped, erasureStripeDrives: stripePref };
    }
    return { ...p, ecParity: clamped };
  });
  return {
    ...data,
    serverPools: nextPools,
    ecParity: nextPools[0].ecParity,
  };
}

export function migrateClusterData(data: any): ClusterNodeData {
  if (Array.isArray(data.serverPools) && data.serverPools.length > 0) {
    return normalizeClusterPoolsEc(data as ClusterNodeData);
  }
  // Old pre-pool configs had top-level nodeCount/drivesPerNode but those values
  // are unreliable legacy noise. Always use canonical defaults for migrated pools.
  const legacyEc = typeof data.ecParity === "number" ? data.ecParity : undefined;
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
  const stripe = effectiveStripeSize(pool.nodeCount * pool.drivesPerNode, pool.erasureStripeDrives ?? null);
  pool.ecParity = clampParityToValidStripe(
    stripe,
    legacyEc ?? minioDefaultStandardParity(stripe),
  );
  const { nodeCount: _n, drivesPerNode: _d, diskSizeTb: _t, ecParity: _e, ecParityUpgradePolicy: _p, ...rest } = data;
  return normalizeClusterPoolsEc({
    ...rest,
    serverPools: [pool],
    ecParity: pool.ecParity,
  } as ClusterNodeData);
}
