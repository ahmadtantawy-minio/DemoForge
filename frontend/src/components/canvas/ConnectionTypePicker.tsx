import { useEffect, useRef } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import type { ConnectionType } from "../../types";

const connectionColors: Record<string, string> = {
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

const connectionLabels: Record<string, string> = {
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

export default function ConnectionTypePicker() {
  const pendingConnection = useDiagramStore((s) => s.pendingConnection);
  const completePendingConnection = useDiagramStore((s) => s.completePendingConnection);
  const setPendingConnection = useDiagramStore((s) => s.setPendingConnection);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!pendingConnection) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPendingConnection(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [pendingConnection, setPendingConnection]);

  if (!pendingConnection) return null;

  const { validTypes, sourcePos, targetPos } = pendingConnection;
  const midX = (sourcePos.x + targetPos.x) / 2 + 70;
  const midY = (sourcePos.y + targetPos.y) / 2 + 20;

  return (
    <div
      ref={ref}
      className="absolute z-50 bg-popover border border-border rounded-lg shadow-lg p-2 min-w-[140px]"
      style={{
        left: midX,
        top: midY,
        transform: "translate(-50%, -50%)",
      }}
    >
      <div className="text-xs font-medium text-muted-foreground mb-1.5 px-1">
        Connection Type
      </div>
      <div className="flex flex-col gap-1">
        {validTypes.map((type) => {
          const color = connectionColors[type] ?? "#6b7280";
          const label = connectionLabels[type] ?? type;
          return (
            <button
              key={type}
              className="flex items-center gap-2 px-2 py-1.5 rounded text-sm hover:bg-accent transition-colors text-left"
              onClick={() => completePendingConnection(type)}
            >
              <span
                className="w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: color }}
              />
              <span className="text-foreground">{label}</span>
            </button>
          );
        })}
      </div>
      <button
        className="mt-1 w-full text-xs text-muted-foreground hover:text-foreground py-1 transition-colors"
        onClick={() => setPendingConnection(null)}
      >
        Cancel
      </button>
    </div>
  );
}
