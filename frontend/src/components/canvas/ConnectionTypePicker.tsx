import { useEffect, useRef } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import type { ConnectionType } from "../../types";
import { getConnectionColor, getConnectionLabel } from "../../lib/connectionMeta";
import { ArrowRight, ArrowRightLeft } from "lucide-react";

export default function ConnectionTypePicker() {
  const pendingConnection = useDiagramStore((s) => s.pendingConnection);
  const completePendingConnection = useDiagramStore((s) => s.completePendingConnection);
  const setPendingConnection = useDiagramStore((s) => s.setPendingConnection);
  const swapPendingConnectionDirection = useDiagramStore((s) => s.swapPendingConnectionDirection);
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

  /** Outside-dismiss for the picker only (see DiagramCanvas: pendingConnection must not use window `click`). */
  useEffect(() => {
    if (!pendingConnection) return;
    let cancelled = false;
    let removeListener: (() => void) | undefined;
    const t = window.setTimeout(() => {
      if (cancelled) return;
      const onMouseDown = (e: MouseEvent) => {
        if (cancelled) return;
        const el = e.target as Node | null;
        if (el && ref.current?.contains(el)) return;
        setPendingConnection(null);
      };
      document.addEventListener("mousedown", onMouseDown, true);
      removeListener = () => document.removeEventListener("mousedown", onMouseDown, true);
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
      removeListener?.();
    };
  }, [pendingConnection, setPendingConnection]);

  if (!pendingConnection) return null;

  const { directedOptions, clusterFlowLabels, allowSwapDirection } = pendingConnection;

  // Position at center of viewport for reliable placement regardless of zoom/pan
  return (
    <div
      ref={ref}
      data-connection-type-picker
      className="fixed z-[10001] bg-popover border border-border rounded-lg shadow-lg p-2 min-w-[200px] max-w-[320px]"
      style={{
        left: "50%",
        top: "40%",
        transform: "translate(-50%, -50%)",
      }}
    >
      <div className="text-xs font-medium text-muted-foreground mb-1.5 px-1">
        Connection Type
      </div>
      {allowSwapDirection && clusterFlowLabels && !directedOptions && (
        <div className="mb-2 rounded-md border border-border bg-muted/40 px-2 py-1.5 text-xs">
          <div className="text-muted-foreground mb-1">Diagram direction (source → target)</div>
          <div className="font-medium text-foreground flex items-center gap-1.5 flex-wrap leading-snug">
            <span className="min-w-0 break-words">{clusterFlowLabels.sourceLabel}</span>
            <ArrowRight className="w-3.5 h-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 break-words">{clusterFlowLabels.targetLabel}</span>
          </div>
          <button
            type="button"
            className="mt-2 w-full flex items-center justify-center gap-1.5 rounded border border-border bg-background px-2 py-1 text-[11px] font-medium text-foreground hover:bg-accent transition-colors"
            onClick={() => swapPendingConnectionDirection()}
          >
            <ArrowRightLeft className="w-3.5 h-3.5 shrink-0" aria-hidden />
            Swap direction
          </button>
        </div>
      )}
      <div className="flex flex-col gap-0.5">
        {directedOptions ? (
          // Show direction-aware options
          directedOptions.map((opt, i) => {
            const color = getConnectionColor(opt.type);
            const typeLabel = getConnectionLabel(opt.type);
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
            const color = getConnectionColor(type);
            const label = getConnectionLabel(type);
            const flowHint =
              clusterFlowLabels && !directedOptions
                ? `${clusterFlowLabels.sourceLabel} → ${clusterFlowLabels.targetLabel}`
                : null;
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
                <div className="flex flex-col min-w-0">
                  <span className="text-foreground font-medium">{label}</span>
                  {flowHint && (
                    <span className="text-[10px] text-muted-foreground mt-0.5 leading-tight break-words">
                      {flowHint}
                    </span>
                  )}
                </div>
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
