import { useEffect, useState, useRef } from "react";
import { useDemoStore } from "../../stores/demoStore";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

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

interface CockpitData {
  demo_id: string;
  clusters: ClusterStats[];
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

  // Render as a right-side panel (replaces PropertiesPanel when cockpit is on)
  return (
    <div className="h-full bg-card border-l border-border overflow-y-auto">
      <div className="p-3">
        <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Cockpit
        </div>
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
