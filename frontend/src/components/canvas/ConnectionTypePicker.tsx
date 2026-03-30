import { useEffect, useRef } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import type { ConnectionType } from "../../types";
import { connectionColors, connectionLabels } from "../../lib/connectionMeta";
import { ArrowRight } from "lucide-react";

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

  const { directedOptions } = pendingConnection;

  // Position at center of viewport for reliable placement regardless of zoom/pan
  return (
    <div
      ref={ref}
      className="fixed z-50 bg-popover border border-border rounded-lg shadow-lg p-2 min-w-[200px] max-w-[320px]"
      style={{
        left: "50%",
        top: "40%",
        transform: "translate(-50%, -50%)",
      }}
    >
      <div className="text-xs font-medium text-muted-foreground mb-1.5 px-1">
        Connection Type
      </div>
      <div className="flex flex-col gap-0.5">
        {directedOptions ? (
          // Show direction-aware options
          directedOptions.map((opt, i) => {
            const color = connectionColors[opt.type] ?? "#6b7280";
            const typeLabel = connectionLabels[opt.type] ?? opt.type;
            return (
              <button
                key={`${opt.type}-${opt.direction}-${i}`}
                className="flex items-center gap-2 px-2 py-1.5 rounded text-sm hover:bg-accent transition-colors text-left"
                onClick={() => completePendingConnection(opt.type, opt.direction)}
              >
                <span
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                <div className="flex flex-col min-w-0">
                  <span className="text-foreground font-medium">{typeLabel}</span>
                  <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                    <ArrowRight className="w-3 h-3 inline" />
                    {opt.label}
                  </span>
                </div>
              </button>
            );
          })
        ) : (
          // Legacy: simple type list without direction
          pendingConnection.validTypes.map((type) => {
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
          })
        )}
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
