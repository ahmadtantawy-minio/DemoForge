import { useState, useCallback } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, useStoreApi, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";
import type { ComponentEdgeData, ConnectionType } from "../../../types";
import { connectionColors, connectionLabels } from "../../../lib/connectionMeta";

export default function AnimatedDataEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd,
}: EdgeProps) {
  const { deleteElements } = useReactFlow();
  const [hovered, setHovered] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const edgeData = data as ComponentEdgeData | undefined;
  const connectionType = (edgeData?.connectionType ?? "data") as string;
  const status = edgeData?.status ?? "idle";
  const configStatus = (edgeData as any)?.configStatus as string | undefined; // "pending" | "applied" | "failed" | "paused" | undefined
  const configError = (edgeData as any)?.configError as string | undefined;
  const color = connectionColors[connectionType] ?? "#6b7280";
  const connConfig = (edgeData as any)?.connectionConfig as Record<string, any> | undefined;
  // For structured-data edges, show format + scenario (e.g. "JSON · E-commerce Orders")
  let formatLabel: string | null = null;
  if (connectionType === "structured-data" && connConfig) {
    const parts: string[] = [];
    if (connConfig.format) parts.push((connConfig.format as string).toUpperCase());
    if (connConfig.scenario) {
      const scenarioName = (connConfig.scenario as string)
        .replace(/-/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
      parts.push(scenarioName);
    }
    formatLabel = parts.length > 0 ? parts.join(" · ") : null;
  }
  const label = edgeData?.label || formatLabel || connectionLabels[connectionType] || "";

  const isBidirectional = (edgeData as any)?.connectionConfig?.direction === "bidirectional" ||
    connectionType === "cluster-site-replication";
  const isFailover = connectionType === "failover";
  const failoverRole = (edgeData as any)?.connectionConfig?.role as string | undefined;
  const failoverActive = (edgeData as any)?.failoverActive as boolean | undefined;
  // For failover edges: active = solid + animated, standby = dashed + dimmed
  const isFailoverStandby = isFailover && failoverActive === false;
  const isFailoverActive = isFailover && failoverActive === true;
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
          markerWidth="8"
          markerHeight="8"
          refX="8"
          refY="4"
          orient="auto"
          markerUnits="userSpaceOnUse"
        >
          <path d="M0,0 L8,4 L0,8" fill="none" stroke={color} strokeWidth="1.5" />
        </marker>
        {isBidirectional && (
          <marker
            id={markerStartId}
            markerWidth="8"
            markerHeight="8"
            refX="0"
            refY="4"
            orient="auto-start-reverse"
            markerUnits="userSpaceOnUse"
          >
            <path d="M8,0 L0,4 L8,8" fill="none" stroke={color} strokeWidth="1.5" />
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
          stroke: isFailoverActive ? "#22c55e" : isFailoverStandby ? "#6b7280" : configStatus === "failed" ? "#ef4444" : color,
          strokeWidth: isFailoverActive ? 2.5 : 2,
          strokeOpacity: isFailoverStandby ? 0.3 : configStatus === "pending" || configStatus === "paused" ? 0.4 : configStatus === "failed" ? 0.5 : 0.8,
          strokeDasharray: isFailoverStandby ? "4 4" : configStatus === "failed" ? "4 4" : configStatus === "pending" || configStatus === "paused" ? "6 4" : undefined,
          markerEnd: `url(#${markerId})`,
          markerStart: isBidirectional ? `url(#${markerStartId})` : undefined,
        }}
      />
      {(status === "active" || configStatus === "applied" || isFailoverActive) && (
        <>
          <circle r="3" fill={color} opacity={0.8}>
            <animateMotion
              dur="2.5s"
              repeatCount="indefinite"
              path={edgePath}
              keyPoints="0;1"
              keyTimes="0;1"
              calcMode="linear"
            />
          </circle>
          {isBidirectional && (
            <circle r="3" fill={color} opacity={0.6}>
              <animateMotion
                dur="2.5s"
                repeatCount="indefinite"
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
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
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
            {isFailoverActive && (
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" title="Active — traffic routing here" />
            )}
            {isFailoverStandby && (
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 shrink-0" title="Standby — ready for failover" />
            )}
            {label}
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
