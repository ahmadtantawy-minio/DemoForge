import { useState, useCallback } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, useStoreApi, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";
import type { ComponentEdgeData, ConnectionType } from "../../../types";

const connectionColors: Record<ConnectionType, string> = {
  s3: "#3b82f6",
  http: "#6b7280",
  metrics: "#22c55e",
  replication: "#a855f7",
  "site-replication": "#d946ef",
  "load-balance": "#f97316",
  data: "#6b7280",
  "metrics-query": "#22c55e",
  tiering: "#eab308",
  "file-push": "#06b6d4",
};

const connectionLabels: Record<ConnectionType, string> = {
  s3: "S3",
  http: "HTTP",
  metrics: "Metrics",
  replication: "Replication",
  "site-replication": "Site Replication",
  "load-balance": "Load Balance",
  data: "Data",
  "metrics-query": "PromQL",
  tiering: "Tiering",
  "file-push": "File Push",
};

export default function AnimatedDataEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd,
}: EdgeProps) {
  const { deleteElements } = useReactFlow();
  const [hovered, setHovered] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const edgeData = data as ComponentEdgeData | undefined;
  const connectionType = (edgeData?.connectionType ?? "data") as ConnectionType;
  const status = edgeData?.status ?? "idle";
  const color = connectionColors[connectionType] ?? "#6b7280";
  const label = edgeData?.label || connectionLabels[connectionType] || "";

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
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
        style={{ stroke: color, strokeWidth: 2, strokeOpacity: 0.8 }}
        markerEnd={markerEnd}
      />
      {status === "active" && (
        <circle r="4" fill={color}>
          <animateMotion dur="2s" repeatCount="indefinite" path={edgePath} />
        </circle>
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
            className="nodrag nopan px-1.5 py-0.5 text-[10px] font-medium rounded"
          >
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
