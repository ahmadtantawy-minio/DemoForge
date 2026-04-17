import type { ConnectionConfigField } from "../../types";

/** Config schemas for cluster-level connection types (not in component manifests). */
export const clusterConfigSchemas: Record<string, ConnectionConfigField[]> = {
  "cluster-replication": [
    { key: "source_bucket", label: "Source Bucket", type: "string", default: "demo-bucket", required: false, options: [], description: "" },
    { key: "target_bucket", label: "Target Bucket", type: "string", default: "demo-bucket", required: false, options: [], description: "" },
    { key: "replication_mode", label: "Mode", type: "select", default: "async", required: false, options: ["async", "sync"], description: "async = eventually consistent, sync = write-through" },
    { key: "direction", label: "Direction", type: "select", default: "one-way", required: false, options: ["one-way", "bidirectional"], description: "" },
    { key: "bandwidth_limit", label: "Bandwidth Limit (MB/s)", type: "string", default: "0", required: false, options: [], description: "0 = unlimited" },
  ],
  "cluster-site-replication": [],
  "cluster-tiering": [
    { key: "source_bucket", label: "Source Bucket (Hot)", type: "string", default: "data", required: false, options: [], description: "" },
    { key: "tier_bucket", label: "Tier Bucket (Cold)", type: "string", default: "tiered", required: false, options: [], description: "" },
    { key: "tier_name", label: "Tier Name", type: "string", default: "COLD-TIER", required: false, options: [], description: "" },
    { key: "transition_days", label: "Transition After (days)", type: "string", default: "30", required: false, options: [], description: "" },
    { key: "policy_name", label: "Policy Name", type: "string", default: "auto-tier", required: false, options: [], description: "" },
  ],
};
