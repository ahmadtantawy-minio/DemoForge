import { describe, expect, it } from "vitest";
import {
  MINIO_POOL_DRIVES_PER_NODE_OPTIONS,
  MINIO_POOL_NODE_COUNT_OPTIONS,
  drivesPerNodeOptionsForPool,
  minDrivesPerNodeForEc,
  minioEcSettingOptions,
  validMinioStandardParities,
} from "./erasure";

describe("MinIO pool topology helpers", () => {
  it("offers 3-node pools in the node count picker", () => {
    expect(MINIO_POOL_NODE_COUNT_OPTIONS).toContain(3);
    expect(MINIO_POOL_NODE_COUNT_OPTIONS).toContain(1);
  });

  it("requires 4 drives per node for single-node EC pools", () => {
    expect(minDrivesPerNodeForEc(1)).toBe(4);
    expect(drivesPerNodeOptionsForPool(1)).toEqual([4, 6, 8, 12, 16]);
  });

  it("requires 2 drives per node for 3-node EC pools", () => {
    expect(minDrivesPerNodeForEc(3)).toBe(2);
    expect(minDrivesPerNodeForEc(2)).toBe(2);
    expect(minDrivesPerNodeForEc(4)).toBe(1);
  });

  it("offers 3 drives per node in the pool picker", () => {
    expect(MINIO_POOL_DRIVES_PER_NODE_OPTIONS).toContain(3);
    expect(drivesPerNodeOptionsForPool(4)).toContain(3);
  });

  it("allows EC parity 3 on a 12-drive stripe (3 nodes × 4 drives)", () => {
    expect(validMinioStandardParities(12)).toContain(3);
    const opts = minioEcSettingOptions(12);
    expect(opts.some((o) => o.value === 3)).toBe(true);
  });
});
