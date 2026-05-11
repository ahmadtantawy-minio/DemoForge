import { useState, useCallback } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, useStoreApi, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";
import type { ComponentEdgeData } from "../../../types";
import { getConnectionColor } from "../../../lib/connectionMeta";
import { nonemptyTrim } from "../../../lib/utils";
import { useDemoStore } from "../../../stores/demoStore";


export default function AnimatedDataEdge({
  id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd,
}: EdgeProps) {
  const { deleteElements, getNode } = useReactFlow();
  const { demos, activeDemoId } = useDemoStore();
  const isDemoRunning = demos.find((d) => d.id === activeDemoId)?.status === "running";
  const [hovered, setHovered] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const edgeData = data as ComponentEdgeData | undefined;
  const connectionType = (edgeData?.connectionType ?? "data") as string;
  const status = edgeData?.status ?? "idle";
  const configStatus = (edgeData as any)?.configStatus as string | undefined; // "pending" | "applied" | "failed" | "paused" | undefined
  const configError = (edgeData as any)?.configError as string | undefined;
  const color = getConnectionColor(connectionType);
  const connConfig = (edgeData as any)?.connectionConfig as Record<string, any> | undefined;

  // For structured-data edges, build a rich label from edge config + source node config
  // e.g. "PARQUET · Ecommerce Orders → data-lake-1"
  let formatLabel: string | null = null;
  if (connectionType === "structured-data") {
    const sourceNode = source ? getNode(source) : undefined;
    const nodeConfig = (sourceNode?.data as any)?.config as Record<string, string> | undefined;

    // Resolve write mode: node config > default
    const writeMode = nodeConfig?.DG_WRITE_MODE || "iceberg";
    // Resolve format: edge config > node config > default
    const fmt = connConfig?.format || nodeConfig?.DG_FORMAT || "parquet";
    // Resolve scenario: edge config > node config > default
    const scenario = connConfig?.scenario || nodeConfig?.DG_SCENARIO || "ecommerce-orders";
    // Target bucket from edge config
    const bucket = connConfig?.target_bucket;

    const parts: string[] = [];
    if (writeMode === "raw") {
      parts.push(`${fmt.toUpperCase()} Raw`);
    } else {
      parts.push("Iceberg");
    }
    if (scenario) {
      parts.push(scenario.replace(/-/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()));
    }
    let base = parts.length > 0 ? parts.join(" · ") : null;
    if (base && bucket) base += ` → ${bucket}`;
    formatLabel = base;
  }

  let webhookEdgeLabel: string | null = null;
  if (connectionType === "webhook") {
    const parts = [connConfig?.webhook_bucket, connConfig?.webhook_events].filter(Boolean);
    webhookEdgeLabel = parts.length > 0 ? parts.map(String).join(" · ") : null;
  }

  const tierRole = connConfig?.tier_role as string | undefined;
  // Persisted demos sometimes drop protocol/latency/bandwidth; infer from STX tier_role for S3 edges
  let effProtocol = nonemptyTrim((edgeData as any)?.protocol) ?? "";
  let effLatency = nonemptyTrim((edgeData as any)?.latency) ?? "";
  let effBandwidth = nonemptyTrim((edgeData as any)?.bandwidth) ?? "";
  if (connectionType === "s3" && tierRole === "g35-cmx") {
    if (!effProtocol) effProtocol = "NVMe-oF / RDMA";
    if (!effLatency) effLatency = "~200-500 μs";
    if (!effBandwidth) effBandwidth = "800 Gb/s";
  } else if (connectionType === "s3" && tierRole === "g4-archive") {
    if (!effProtocol) effProtocol = "S3 over TCP";
    if (!effLatency) effLatency = "~5–50 ms";
    if (!effBandwidth) effBandwidth = "100 Gb/s";
  }

  // Protocol-based edge styling
  const protoStyle: React.CSSProperties = (() => {
    if (!effProtocol) return {};
    if (effProtocol.includes("RDMA") || effProtocol.includes("NVMe")) return { stroke: "#1D9E75", strokeWidth: 2.5 };
    if (effProtocol.includes("S3") && effProtocol.includes("TCP")) return { stroke: "#f59e0b", strokeWidth: 2.2, strokeDasharray: "5 3" };
    if (effProtocol.includes("gRPC")) return { stroke: "#378ADD", strokeWidth: 1.5, strokeDasharray: "6 3" };
    if (effProtocol === "HTTP") return { stroke: "var(--color-muted-foreground, #666)", strokeWidth: 1, strokeDasharray: "2 2" };
    return {};
  })();

  // External-system data flow animation
  const sourceNode = getNode(source);
  const targetNode = target ? getNode(target) : undefined;
  const sourceComponentId = (sourceNode?.data as any)?.componentId as string | undefined;
  const targetComponentId = (targetNode?.data as any)?.componentId as string | undefined;
  const sourceHealth = (sourceNode?.data as any)?.health as string | undefined;
  const isExternalSystem = sourceComponentId === "external-system";
  const isExternalActive = isExternalSystem && isDemoRunning && (sourceHealth === "healthy");

  // Pace from generation_mode stored on edge connectionConfig when scenario is selected
  const generationMode = connConfig?.generation_mode as string | undefined;
  // stream → fast/dense, batch_then_stream → medium, batch/default → slow
  const paceDur = generationMode === "stream" ? 1.0 : generationMode === "batch" ? 3.5 : 1.8;
  const paceParticles = generationMode === "stream" ? 4 : generationMode === "batch" ? 2 : 3;

  let externalSystemEdgeFallback: string | null = null;
  if (
    (connectionType === "s3" || connectionType === "aistor-tables") &&
    sourceComponentId === "external-system"
  ) {
    const sinkRaw =
      (connConfig?.es_sink_mode as string | undefined) ?? (sourceNode?.data as { config?: Record<string, string> } | undefined)?.config?.ES_SINK_MODE;
    const sink = sinkRaw === "files_only" ? "files_only" : "files_and_iceberg";
    const sinkTag =
      sink === "files_only" ? "Raw only" : connectionType === "aistor-tables" ? "Iceberg" : "Catalog";
    const parts: string[] = [sinkTag];
    if (sink === "files_only") {
      const srcCfg = (sourceNode?.data as { config?: Record<string, string> } | undefined)?.config ?? {};
      const fmt = (
        nonemptyTrim(srcCfg.ES_DG_FORMAT) ??
        nonemptyTrim(srcCfg.DG_FORMAT) ??
        nonemptyTrim(connConfig?.format as string | undefined) ??
        "csv"
      ).toUpperCase();
      const b = nonemptyTrim(connConfig?.target_bucket as string | undefined) ?? nonemptyTrim(connConfig?.bucket as string | undefined);
      parts.push(fmt);
      if (b) parts.push(b);
    } else if (generationMode) {
      parts.push(String(generationMode));
    }
    externalSystemEdgeFallback = parts.join(" · ");
  }

  let sparkJobS3Fallback: string | null = null;
  if (
    (connectionType === "s3" || connectionType === "aistor-tables") &&
    targetComponentId === "spark-etl-job" &&
    targetNode
  ) {
    const jc = ((targetNode.data as any)?.config ?? {}) as Record<string, string>;
    const rawFmt = String(jc.RAW_INPUT_FORMAT || jc.INPUT_FORMAT || "csv").toLowerCase();
    const fileLabel = rawFmt === "json" ? "JSON" : "CSV";
    const table = String(jc.ICEBERG_TARGET_TABLE || "events_from_raw").trim() || "events_from_raw";
    const br = (connConfig?.spark_bucket_role as string | undefined)?.toLowerCase() || "";
    const sr = (connConfig?.spark_sink_role as string | undefined)?.toLowerCase() || "";
    const isOut =
      sr === "output" || br === "warehouse" || br === "curated" || br === "output";
    sparkJobS3Fallback = isOut ? `Iceberg → ${table}` : `${fileLabel} → ${table}`;
  }

  let sparkSparkS3Fallback: string | null = null;
  if (connectionType === "s3" && targetComponentId === "spark" && sourceComponentId === "minio") {
    const br = (connConfig?.spark_bucket_role as string | undefined)?.toLowerCase() || "";
    const rawB = (connConfig?.raw_bucket as string | undefined)?.trim();
    const wh = (connConfig?.warehouse_bucket as string | undefined)?.trim() || "warehouse";
    if (br === "raw" || br === "landing") {
      sparkSparkS3Fallback = rawB ? `S3 · raw (${rawB})` : "S3 · raw";
    } else if (br === "warehouse" || br === "curated") {
      sparkSparkS3Fallback = `S3 · warehouse (${wh})`;
    } else if (rawB) {
      sparkSparkS3Fallback = wh ? `S3 · raw (${rawB}) + wh (${wh})` : `S3 · raw (${rawB})`;
    } else {
      sparkSparkS3Fallback = `S3 · warehouse (${wh})`;
    }
  }

  let sparkSubmitFallback: string | null = null;
  if (connectionType === "spark-submit") {
    sparkSubmitFallback = "Spark submit";
  }

  // Spark ETL jobs read from MinIO (raw/landing) and write back (warehouse/Iceberg) over the same S3/Tables path.
  const isSparkEtlMinioDataEdge =
    (connectionType === "s3" || connectionType === "aistor-tables") &&
    ((sourceComponentId === "spark-etl-job" && targetComponentId === "minio") ||
      (targetComponentId === "spark-etl-job" && sourceComponentId === "minio"));

  const isBidirectional =
    (edgeData as any)?.connectionConfig?.direction === "bidirectional" ||
    connectionType === "site-replication" ||
    connectionType === "cluster-site-replication" ||
    isSparkEtlMinioDataEdge;
  const isFailover = connectionType === "failover";
  const failoverRole = (edgeData as any)?.connectionConfig?.role as string | undefined;
  const failoverActive = (edgeData as any)?.failoverActive as boolean | undefined;
  // For failover edges: active = solid + animated, standby = dashed + dimmed
  const isFailoverStandby = isFailover && failoverActive === false;
  const isFailoverActive = isFailover && failoverActive === true;

  // nginx-backend: derive style from source node's config.mode; failover role from edge index
  const isNginxBackend = connectionType === "nginx-backend";
  const nginxSourceNode = isNginxBackend ? sourceNode : undefined;
  const nginxMode = isNginxBackend ? ((nginxSourceNode?.data as any)?.config?.mode as string | undefined) ?? "round-robin" : undefined;
  const isNginxFailover = isNginxBackend && nginxMode === "failover";
  const allRfEdges = useStoreApi().getState().edges;
  const nginxEdgeIndex = isNginxFailover
    ? allRfEdges.filter((e) => e.source === source && (e.data as any)?.connectionType === "nginx-backend").findIndex((e) => e.id === id)
    : -1;
  const isNginxFailoverActive = isNginxFailover && nginxEdgeIndex === 0;
  const isNginxFailoverStandby = isNginxFailover && nginxEdgeIndex > 0;

  // For nginx-backend, derive label from nginx node variant
  let nginxLabel: string | null = null;
  if (isNginxBackend) {
    if (isNginxFailoverActive) nginxLabel = "Active";
    else if (isNginxFailoverStandby) nginxLabel = "Standby";
    else nginxLabel = "Load Balance";
  }

  // Text shown in the pill: custom label and/or derived labels only — no default connection-type name (e.g. "S3").
  const labelText =
    nonemptyTrim(edgeData?.label) ??
    formatLabel ??
    webhookEdgeLabel ??
    nginxLabel ??
    externalSystemEdgeFallback ??
    sparkJobS3Fallback ??
    sparkSparkS3Fallback ??
    sparkSubmitFallback ??
    "";

  const hasInlineStatus =
    configStatus === "applied" ||
    configStatus === "failed" ||
    configStatus === "pending" ||
    configStatus === "paused" ||
    isFailoverActive ||
    isFailoverStandby ||
    isNginxFailoverActive ||
    isNginxFailoverStandby;

  /** Hide the edge label pill when there is nothing to show (no text and no status badges). */
  const showConnectionLabelPill = labelText.length > 0 || hasInlineStatus;

  const markerId = `arrow-${id}`;
  const markerStartId = `arrow-start-${id}`;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      {/* Arrow marker definitions */}
      <defs>
        <marker
          id={markerId}
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L6,3 L0,6 Z" fill={color} />
        </marker>
        {isBidirectional && (
          <marker
            id={markerStartId}
            markerWidth="6"
            markerHeight="6"
            refX="1"
            refY="3"
            orient="auto-start-reverse"
          >
            <path d="M6,0 L0,3 L6,6 Z" fill={color} />
          </marker>
        )}
      </defs>
      {/* Invisible wide hit area for hover detection */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{ cursor: "pointer" }}
      />
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: isFailoverActive || isNginxFailoverActive ? "#22c55e" : isFailoverStandby || isNginxFailoverStandby ? "#6b7280" : configStatus === "failed" ? "#ef4444" : protoStyle.stroke || color,
          strokeWidth: isFailoverActive || isNginxFailoverActive ? 2.5 : protoStyle.strokeWidth || 2,
          strokeOpacity: isFailoverStandby || isNginxFailoverStandby ? 0.3 : configStatus === "pending" || configStatus === "paused" ? 0.4 : configStatus === "failed" ? 0.5 : 0.8,
          strokeDasharray: isFailoverStandby || isNginxFailoverStandby ? "4 4" : configStatus === "failed" ? "4 4" : configStatus === "pending" || configStatus === "paused" ? "6 4" : protoStyle.strokeDasharray || undefined,
          markerEnd: `url(#${markerId})`,
          markerStart: isBidirectional ? `url(#${markerStartId})` : undefined,
        }}
      />
      {isDemoRunning && (status === "active" || isFailoverActive || isNginxFailoverActive) && (
        <>
          <circle r="3" fill={color} opacity={0.8}>
            <animateMotion
              id={`fwd-${id}`}
              dur="1.8s"
              begin={`0s; fwd-${id}.end + 2s`}
              repeatCount="1"
              path={edgePath}
              keyPoints="0;1"
              keyTimes="0;1"
              calcMode="linear"
            />
          </circle>
          {isBidirectional && (
            <circle r="3" fill={color} opacity={0.6}>
              <animateMotion
                id={`rev-${id}`}
                dur="1.8s"
                begin={`0.9s; rev-${id}.end + 2s`}
                repeatCount="1"
                path={edgePath}
                keyPoints="1;0"
                keyTimes="0;1"
                calcMode="linear"
              />
            </circle>
          )}
        </>
      )}
      {/* External-system: continuous data stream particles scaled to generation pace */}
      {isExternalActive && (
        <>
          {Array.from({ length: paceParticles }).map((_, i) => {
            const offset = (paceDur / paceParticles) * i;
            return (
              <circle key={i} r="2.5" fill={color} opacity={0.75 - i * 0.1}>
                <animateMotion
                  dur={`${paceDur}s`}
                  begin={`${offset}s`}
                  repeatCount="indefinite"
                  path={edgePath}
                  keyPoints="0;1"
                  keyTimes="0;1"
                  calcMode="linear"
                />
              </circle>
            );
          })}
        </>
      )}
      <EdgeLabelRenderer>
        {showConnectionLabelPill && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY - 12}px)`,
              pointerEvents: "none",
              backgroundColor: `${color}15`,
              border: `1px solid ${color}40`,
              color: color,
            }}
            className="nodrag nopan px-1.5 py-0.5 text-[10px] font-medium rounded flex items-center gap-1"
          >
            {configStatus === "applied" && (
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" title="Config applied — right-click to pause" />
            )}
            {configStatus === "failed" && (
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" title={configError ? `Failed: ${configError}` : "Config failed — right-click to retry"} />
            )}
            {configStatus === "failed" && configError && (
              <span className="text-red-400 max-w-[120px] truncate" title={configError}>
                {configError.replace(/^mc:\s*<ERROR>\s*/i, "").slice(0, 40)}
              </span>
            )}
            {configStatus === "pending" && (
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse shrink-0" title="Applying config..." />
            )}
            {configStatus === "paused" && (
              <svg width="8" height="8" viewBox="0 0 8 8" className="shrink-0" aria-label="Paused — right-click to activate">
                <rect x="1" y="1" width="2" height="6" fill="#eab308" />
                <rect x="5" y="1" width="2" height="6" fill="#eab308" />
              </svg>
            )}
            {(isFailoverActive || isNginxFailoverActive) && (
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" title="Active — traffic routing here" />
            )}
            {(isFailoverStandby || isNginxFailoverStandby) && (
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 shrink-0" title="Standby — ready for failover" />
            )}
            {labelText}
          </div>
        )}
        {(effProtocol || effLatency || effBandwidth) && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, 0) translate(${labelX}px,${labelY - 2}px)`,
              pointerEvents: "none",
            }}
            className="nodrag nopan flex flex-wrap items-center justify-center gap-1 max-w-[min(420px,70vw)]"
          >
            {effProtocol && (
              <span className="text-[9px] font-mono text-teal-100 bg-teal-950/85 px-1.5 py-0.5 rounded whitespace-nowrap border border-teal-400/50 shadow-sm">
                {effProtocol}
              </span>
            )}
            {effLatency && (
              <span className="text-[10px] font-semibold tabular-nums text-amber-50 bg-amber-950 px-1.5 py-0.5 rounded-md whitespace-nowrap border border-amber-300/60 shadow-sm">
                {effLatency}
              </span>
            )}
            {effBandwidth && (
              <span className="text-[9px] font-medium text-sky-100 bg-sky-950/85 px-1.5 py-0.5 rounded whitespace-nowrap border border-sky-400/50 shadow-sm">
                {effBandwidth}
              </span>
            )}
          </div>
        )}
        {hovered && !confirmDelete && (
          <button
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY - 16}px)`,
              pointerEvents: "all",
            }}
            className="nodrag nopan flex items-center justify-center w-4 h-4 rounded-full bg-destructive text-destructive-foreground hover:bg-destructive/80 transition-colors"
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onClick={(e) => { e.stopPropagation(); setConfirmDelete(true); }}
          >
            <X size={10} />
          </button>
        )}
        {confirmDelete && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY - 20}px)`,
              pointerEvents: "all",
            }}
            className="nodrag nopan flex items-center gap-1 bg-popover border border-border rounded px-2 py-1 shadow-lg"
          >
            <span className="text-[10px] text-muted-foreground">Delete?</span>
            <button
              className="px-1.5 py-0.5 text-[10px] bg-destructive text-destructive-foreground rounded hover:bg-destructive/80"
              onClick={() => deleteElements({ edges: [{ id }] })}
            >
              Yes
            </button>
            <button
              className="px-1.5 py-0.5 text-[10px] bg-muted text-muted-foreground rounded hover:bg-accent"
              onClick={() => setConfirmDelete(false)}
            >
              No
            </button>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
}
