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
    {
      key: "source_bucket",
      label: "Hot bucket (ILM source)",
      type: "string",
      default: "data",
      required: false,
      options: [],
      description:
        "Bucket on the hot cluster where data lives before ILM moves it. The lifecycle rule is attached here (`mc ilm rule add hot/…`).",
    },
    {
      key: "cold_bucket",
      label: "Cold bucket (remote)",
      type: "string",
      default: "tiered",
      required: false,
      options: [],
      description:
        "Bucket on the cold cluster passed to `mc admin tier add --bucket`. Created on deploy if missing.",
    },
    {
      key: "tier_prefix",
      label: "Destination prefix",
      type: "string",
      default: "",
      required: false,
      options: [],
      description:
        "Optional key prefix under the cold bucket for transitioned objects (`mc admin tier add --prefix`, trailing slash added if omitted). Leave empty to use the bucket root.",
    },
    {
      key: "tier_name",
      label: "Remote tier name",
      type: "string",
      default: "COLD-TIER",
      required: false,
      options: [],
      description:
        "Name MinIO uses for this remote tier (Tiering → Tiers). ILM transition must reference this exact name—MinIO rejects AWS-only classes like GLACIER unless you defined a tier with that name.",
    },
    {
      key: "transition_days",
      label: "Transition after (days)",
      type: "string",
      default: "30",
      required: false,
      options: [],
      description: "Days without access before objects transition to the cold tier.",
    },
    {
      key: "policy_name",
      label: "ILM policy name",
      type: "string",
      default: "auto-tier",
      required: false,
      options: [],
      description: "Optional policy label for the generated ILM rule.",
    },
  ],
};
