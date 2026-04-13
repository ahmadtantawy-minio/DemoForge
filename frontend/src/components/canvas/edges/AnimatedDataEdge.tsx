import { useState, useCallback } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, useStoreApi, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";
import type { ComponentEdgeData, ConnectionType } from "../../../types";
import { connectionColors, connectionLabels } from "../../../lib/connectionMeta";
import { useDemoStore } from "../../../stores/demoStore";


export default function AnimatedDataEdge({
  id, source, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd,
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
  const color = connectionColors[connectionType] ?? "#6b7280";
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
  const protocol = (edgeData as any)?.protocol as string | undefined;
  const edgeLatency = (edgeData as any)?.latency as string | undefined;
  const edgeBandwidth = (edgeData as any)?.bandwidth as string | undefined;

  // Protocol-based edge styling
  const protoStyle: React.CSSProperties = (() => {
    if (!protocol) return {};
    if (protocol.includes("RDMA") || protocol.includes("NVMe")) return { stroke: "#1D9E75", strokeWidth: 2.5 };
    if (protocol.includes("gRPC")) return { stroke: "#378ADD", strokeWidth: 1.5, strokeDasharray: "6 3" };
    if (protocol === "HTTP") return { stroke: "var(--color-muted-foreground, #666)", strokeWidth: 1, strokeDasharray: "2 2" };
    return {};
  })();

  const isBidirectional = (edgeData as any)?.connectionConfig?.direction === "bidirectional" ||
    connectionType === "site-replication" ||
    connectionType === "cluster-site-replication";
  const isFailover = connectionType === "failover";
  const failoverRole = (edgeData as any)?.connectionConfig?.role as string | undefined;
  const failoverActive = (edgeData as any)?.failoverActive as boolean | undefined;
  // For failover edges: active = solid + animated, standby = dashed + dimmed
  const isFailoverStandby = isFailover && failoverActive === false;
  const isFailoverActive = isFailover && failoverActive === true;

  // nginx-backend: derive style from source node's config.mode; failover role from edge index
  const isNginxBackend = connectionType === "nginx-backend";
  const sourceNode = isNginxBackend ? getNode(source) : undefined;
  const nginxMode = isNginxBackend ? ((sourceNode?.data as any)?.config?.mode as string | undefined) ?? "round-robin" : undefined;
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

  const label = edgeData?.label || formatLabel || nginxLabel || connectionLabels[connectionType] || "";

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
      <EdgeLabelRenderer>
        {label && (
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
            {label}
          </div>
        )}
        {(protocol || edgeLatency || edgeBandwidth) && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, 0) translate(${labelX}px,${labelY - 2}px)`,
              pointerEvents: "none",
            }}
            className="nodrag nopan flex items-center gap-1"
          >
            {protocol && (
              <span className="text-[9px] font-mono text-teal-400/80 bg-teal-500/10 px-1 py-0.5 rounded whitespace-nowrap border border-teal-500/20">
                {protocol}
              </span>
            )}
            {edgeLatency && (
              <span className="text-[9px] text-amber-400/80 bg-amber-500/10 px-1 py-0.5 rounded whitespace-nowrap border border-amber-500/20">
                {edgeLatency}
              </span>
            )}
            {edgeBandwidth && (
              <span className="text-[9px] text-blue-400/80 bg-blue-500/10 px-1 py-0.5 rounded whitespace-nowrap border border-blue-500/20">
                {edgeBandwidth}
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
