import { describe, expect, it } from "vitest";
import { clusterDataPatchAffectsCompose } from "./persistClusterTopology";

describe("clusterDataPatchAffectsCompose", () => {
  it("returns true for topology / compose-driving fields", () => {
    expect(clusterDataPatchAffectsCompose({ serverPools: [] })).toBe(true);
    expect(clusterDataPatchAffectsCompose({ config: { MINIO_EDITION: "ce" } })).toBe(true);
    expect(clusterDataPatchAffectsCompose({ credentials: {} })).toBe(true);
    expect(clusterDataPatchAffectsCompose({ mcpEnabled: true })).toBe(true);
    expect(clusterDataPatchAffectsCompose({ aistorTablesEnabled: true })).toBe(true);
  });

  it("returns false for label-only updates", () => {
    expect(clusterDataPatchAffectsCompose({ label: "x" })).toBe(false);
  });
});
