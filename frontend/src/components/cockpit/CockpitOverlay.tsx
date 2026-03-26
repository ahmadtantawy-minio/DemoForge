import { useEffect, useState, useRef, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { GripHorizontal, X } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:9210";

interface BucketStat {
  name: string;
  objects: number;
  size: number;
}

interface ClusterStats {
  alias: string;
  buckets: BucketStat[];
  throughput: {
    rx_bytes_total?: number;
    tx_bytes_total?: number;
    rx_bytes_per_sec?: number;
    tx_bytes_per_sec?: number;
  };
}

interface HostStats {
  cpu_percent: number;
  memory_mb: number;
  memory_limit_mb: number;
  container_count: number;
}

interface CockpitData {
  demo_id: string;
  clusters: ClusterStats[];
  host_stats?: HostStats;
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0 || !isFinite(bytes)) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function formatRate(bytesPerSec: number): string {
  if (bytesPerSec === 0) return "0";
  const k = 1024;
  if (bytesPerSec < k) return `${bytesPerSec.toFixed(0)} B/s`;
  if (bytesPerSec < k * k) return `${(bytesPerSec / k).toFixed(1)} KB/s`;
  return `${(bytesPerSec / (k * k)).toFixed(1)} MB/s`;
}

export default function CockpitOverlay() {
  const { activeDemoId, demos, cockpitEnabled: enabled } = useDemoStore();
  const [data, setData] = useState<CockpitData | null>(null);
  const prevThroughput = useRef<Record<string, { rx: number; tx: number; ts: number }>>({});

  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isRunning = activeDemo?.status === "running";

  useEffect(() => {
    if (!enabled || !activeDemoId || !isRunning) {
      setData(null);
      return;
    }

    const fetchCockpit = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/cockpit`);
        if (!res.ok) return;
        const json: CockpitData = await res.json();

        // Compute throughput rates from deltas
        const now = Date.now();
        for (const cluster of json.clusters) {
          const prev = prevThroughput.current[cluster.alias];
          const rxTotal = cluster.throughput.rx_bytes_total || 0;
          const txTotal = cluster.throughput.tx_bytes_total || 0;

          if (prev) {
            const dt = (now - prev.ts) / 1000; // seconds
            if (dt > 0) {
              cluster.throughput.rx_bytes_per_sec = Math.max(0, (rxTotal - prev.rx) / dt);
              cluster.throughput.tx_bytes_per_sec = Math.max(0, (txTotal - prev.tx) / dt);
            }
          }

          prevThroughput.current[cluster.alias] = { rx: rxTotal, tx: txTotal, ts: now };
        }

        setData(json);
      } catch {
        // Silently fail — cockpit is non-critical
      }
    };

    fetchCockpit();
    const interval = setInterval(fetchCockpit, 4000);
    return () => clearInterval(interval);
  }, [enabled, activeDemoId, isRunning]);

  const toggleCockpit = useDemoStore((s) => s.toggleCockpit);

  // Draggable position
  const [pos, setPos] = useState({ x: window.innerWidth - 320, y: 60 });
  const dragRef = useRef<{ startX: number; startY: number; posX: number; posY: number } | null>(null);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startY: e.clientY, posX: pos.x, posY: pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - 280, dragRef.current.posX + ev.clientX - dragRef.current.startX)),
        y: Math.max(0, Math.min(window.innerHeight - 100, dragRef.current.posY + ev.clientY - dragRef.current.startY)),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [pos]);

  return (
    <div
      className="fixed z-50 w-[280px] max-h-[60vh] bg-card/95 backdrop-blur border border-border rounded-lg shadow-xl overflow-hidden flex flex-col"
      style={{ left: pos.x, top: pos.y }}
    >
      {/* Draggable header */}
      <div
        className="flex items-center justify-between px-3 py-1.5 bg-muted/50 border-b border-border cursor-move select-none"
        onMouseDown={onDragStart}
      >
        <div className="flex items-center gap-1.5">
          <GripHorizontal className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Cockpit</span>
        </div>
        <button
          className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-accent transition-colors"
          onClick={toggleCockpit}
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="overflow-y-auto p-3">
        {data?.host_stats && (
          <div className="mb-3 pb-3 border-b border-border">
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
              Host Resources ({data.host_stats.container_count} containers)
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
              <div className="flex justify-between col-span-2">
                <span className="text-muted-foreground">CPU</span>
                <span className="text-foreground font-mono">{data.host_stats.cpu_percent.toFixed(1)}%</span>
              </div>
              <div className="flex justify-between col-span-2">
                <span className="text-muted-foreground">Memory</span>
                <span className="text-foreground font-mono">
                  {data.host_stats.memory_mb.toFixed(0)} MB
                  {data.host_stats.memory_limit_mb > 0 && (
                    <span className="text-muted-foreground"> / {data.host_stats.memory_limit_mb.toFixed(0)} MB</span>
                  )}
                </span>
              </div>
            </div>
          </div>
        )}
        {!data || data.clusters.length === 0 ? (
          <div className="text-xs text-muted-foreground">
            {!isRunning ? "Deploy a demo to see cockpit data" : "Loading cluster data..."}
          </div>
        ) : (
          data.clusters.map((cluster) => {
            const totalObjects = cluster.buckets.reduce((sum, b) => sum + b.objects, 0);
            const rxRate = cluster.throughput.rx_bytes_per_sec || 0;
            const txRate = cluster.throughput.tx_bytes_per_sec || 0;

            return (
              <div key={cluster.alias} className="mb-3 last:mb-0">
                <div className="text-xs font-medium text-foreground mb-1">{cluster.alias}</div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
                  {cluster.buckets.map((b) => (
                    <div key={b.name} className="flex justify-between col-span-2">
                      <span className="text-muted-foreground truncate">{b.name}</span>
                      <span className="text-foreground font-mono">
                        {b.objects.toLocaleString()} obj ({formatBytes(b.size)})
                      </span>
                    </div>
                  ))}
                  {cluster.buckets.length === 0 && (
                    <div className="text-muted-foreground col-span-2">No buckets</div>
                  )}
                  <div className="col-span-2 flex gap-3 mt-1 pt-1 border-t border-border/50">
                    <span className="text-green-400">
                      ↑ {formatRate(txRate)}
                    </span>
                    <span className="text-blue-400">
                      ↓ {formatRate(rxRate)}
                    </span>
                    <span className="text-muted-foreground ml-auto">
                      {totalObjects.toLocaleString()} total
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// Re-export so App.tsx doesn't need to change the import
