/** Bucket routing from canvas edges (read-only); compose injects env from the same edge config. */
export function getEventProcessorConnectionRouting(
  selectedNodeId: string,
  edges: { source: string; target: string; data?: unknown }[]
) {
  let webhookBucket = "";
  let webhookPrefix = "";
  let webhookEvents = "";
  let s3TargetBucket = "";
  let icebergWarehouse = "";

  for (const e of edges) {
    const d = (e.data ?? {}) as { connectionType?: string; connectionConfig?: Record<string, unknown> };
    const ct = d.connectionType;
    const cfg = d.connectionConfig ?? {};
    if (ct === "webhook" && (e.target === selectedNodeId || e.source === selectedNodeId)) {
      webhookBucket = String(cfg.webhook_bucket ?? "");
      webhookPrefix = String(cfg.webhook_prefix ?? "");
      webhookEvents = String(cfg.webhook_events ?? "");
    }
    if ((ct === "s3" || ct === "aistor-tables") && e.source === selectedNodeId) {
      s3TargetBucket = String(cfg.target_bucket || cfg.bucket || cfg.sink_bucket || "");
      if (ct === "aistor-tables") icebergWarehouse = String(cfg.warehouse ?? "");
    }
  }
  return { webhookBucket, webhookPrefix, webhookEvents, s3TargetBucket, icebergWarehouse };
}
