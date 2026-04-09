import { useEffect, useState, useRef, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { GripHorizontal, X } from "lucide-react";
import ClusterHealthPanel from "./ClusterHealthPanel";

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

// mc admin info types
interface AdminDrive {
  endpoint?: string;
  state?: string;
  uuid?: string;
  path?: string;
}

interface AdminServer {
  endpoint?: string;
  state?: string;
  drives?: AdminDrive[];
  uptime?: number;
  version?: string;
}

interface AdminInfo {
  mode?: string;
  region?: string;
  sqsARN?: string[];
  servers?: AdminServer[];
  disks?: AdminDrive[];
  backend?: {
    backendType?: string;
    onlineDisks?: number;
    offlineDisks?: number;
    standardSCData?: number;
    standardSCParity?: number;
  };
  usage?: {
    size?: number;
    capacity?: number;
  };
}

interface ClusterHealthResult {
  alias: string;
  info: AdminInfo | null;
  raw?: string;
  status?: "healthy" | "degraded" | "starting" | "unreachable";
  error?: string;
}

interface CockpitHealthData {
  demo_id: string;
  clusters: ClusterHealthResult[];
  error?: string;
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0 || !isFinite(bytes)) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
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

const BASE_WIDTH = 380;

export default function CockpitOverlay() {
  const { activeDemoId, demos, cockpitEnabled: enabled, clusterHealth } = useDemoStore();
  const [data, setData] = useState<CockpitData | null>(null);
  const [healthData, setHealthData] = useState<CockpitHealthData | null>(null);
  const [activeTab, setActiveTab] = useState<"health" | "stats">("health");
  const prevThroughput = useRef<Record<string, { rx: number; tx: number; ts: number }>>({});
  const [clusters, setClusters] = useState<{ id: string; drivesPerNode: number }[]>([]);

  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isRunning = activeDemo?.status === "running";

  // Fetch full demo definition once when active demo changes to get cluster IDs
  useEffect(() => {
    if (!activeDemoId) {
      setClusters([]);
      return;
    }
    fetch(`${API_BASE}/api/demos/${activeDemoId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((demo) => {
        if (demo?.clusters) {
          setClusters(demo.clusters.map((c: any) => ({ id: c.id, drivesPerNode: c.drives_per_node ?? 4 })));
        } else {
          setClusters([]);
        }
      })
      .catch(() => setClusters([]));
  }, [activeDemoId]);

  // Fetch stats data (bucket stats + throughput)
  useEffect(() => {
    if (!enabled || !activeDemoId || !isRunning) {
      setData(null);
      return;
    }

    const fetchCockpit = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/cockpit`);
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          setData({ clusters: [], error: err.detail || `HTTP ${res.status}` } as any);
          return;
        }
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

  // Fetch health data (mc admin info) every 8 seconds
  useEffect(() => {
    if (!enabled || !activeDemoId || !isRunning) {
      setHealthData(null);
      return;
    }

    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/cockpit/health`);
        if (!res.ok) return;
        const json: CockpitHealthData = await res.json();
        setHealthData(json);
      } catch {
        // Silently fail
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 8000);
    return () => clearInterval(interval);
  }, [enabled, activeDemoId, isRunning]);

  const toggleCockpit = useDemoStore((s) => s.toggleCockpit);

  // Draggable position
  const [pos, setPos] = useState({ x: window.innerWidth - 420, y: 60 });
  const dragRef = useRef<{ startX: number; startY: number; posX: number; posY: number } | null>(null);

  // Resizable width
  const [cockpitWidth, setCockpitWidth] = useState(BASE_WIDTH);
  const resizeRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startY: e.clientY, posX: pos.x, posY: pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - cockpitWidth, dragRef.current.posX + ev.clientX - dragRef.current.startX)),
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
  }, [pos, cockpitWidth]);

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeRef.current = { startX: e.clientX, startWidth: cockpitWidth };
    const onMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return;
      const newWidth = Math.max(280, Math.min(700, resizeRef.current.startWidth + (resizeRef.current.startX - ev.clientX)));
      setCockpitWidth(newWidth);
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [cockpitWidth]);

  const scale = cockpitWidth / BASE_WIDTH;

  return (
    <div
      className="fixed z-50 bg-card/95 backdrop-blur border border-border rounded-lg shadow-xl overflow-hidden flex flex-col"
      style={{ left: pos.x, top: pos.y, width: cockpitWidth }}
    >
      {/* Left resize handle */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-primary/30 transition-colors z-10"
        onMouseDown={onResizeStart}
      />

      {/* Draggable header */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border cursor-move select-none"
        onMouseDown={onDragStart}
      >
        <div className="flex items-center gap-1.5">
          <GripHorizontal className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Cockpit</span>
        </div>
        <button
          className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-accent transition-colors"
          onClick={toggleCockpit}
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Tab bar */}
      <div
        className="flex border-b border-border bg-muted/30 select-none"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {(["health", "stats"] as const).map((tab) => (
          <button
            key={tab}
            className={`flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
              activeTab === tab
                ? "text-foreground border-b-2 border-primary bg-card/60"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Scaled content wrapper */}
      <div className="overflow-hidden" style={{ maxHeight: `calc(${scale} * 60vh)` }}>
        <div
          style={{
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            width: BASE_WIDTH,
            maxHeight: "60vh",
            overflowY: "auto",
          }}
          className="p-3"
        >
          {activeTab === "health" ? (
            <HealthTabContent
              healthData={healthData}
              isRunning={isRunning}
              activeDemoId={activeDemoId}
              demoStatus={activeDemo?.status}
            />
          ) : (
            <StatsTabContent
              data={data}
              isRunning={isRunning}
              activeDemoId={activeDemoId}
              clusters={clusters}
              clusterHealth={clusterHealth}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Health Tab ----

function HealthTabContent({
  healthData,
  isRunning,
  activeDemoId,
  demoStatus,
}: {
  healthData: CockpitHealthData | null;
  isRunning: boolean;
  activeDemoId: string | null;
  demoStatus?: string;
}) {
  if (!activeDemoId) {
    return <div className="text-xs text-muted-foreground">No active demo selected</div>;
  }

  if (!isRunning) {
    if (demoStatus === "not_deployed") {
      return <div className="text-xs text-muted-foreground">Not deployed — click Deploy to start</div>;
    }
    if (demoStatus === "stopped") {
      return <div className="text-xs text-muted-foreground">Demo stopped — redeploy to see health data</div>;
    }
    if (demoStatus === "deploying") {
      return <div className="text-xs text-amber-400/80 animate-pulse">Deploying — waiting for cluster...</div>;
    }
    return <div className="text-xs text-muted-foreground">Deploy a demo to see health data</div>;
  }

  if (!healthData) {
    return <div className="text-xs text-muted-foreground">Loading health data...</div>;
  }

  if (healthData.error) {
    return <div className="text-xs text-muted-foreground">{healthData.error}</div>;
  }

  if (healthData.clusters.length === 0) {
    return <div className="text-xs text-muted-foreground">No clusters found in this demo</div>;
  }

  return (
    <div className="space-y-3">
      {healthData.clusters.map((cluster) => (
        <ClusterAdminInfo key={cluster.alias} cluster={cluster} />
      ))}
    </div>
  );
}

function ClusterAdminInfo({ cluster }: { cluster: ClusterHealthResult }) {
  const { alias, info, status, error } = cluster;

  if (!info || status === "unreachable") {
    return (
      <div className="mb-2">
        <div className="text-xs font-medium text-foreground mb-1">{alias}</div>
        <div className="text-[10px] text-red-400/80">
          Unreachable{error ? ` — ${error}` : " — cluster may still be starting"}
        </div>
      </div>
    );
  }

  if (status === "starting") {
    return (
      <div className="mb-2">
        <div className="text-xs font-medium text-foreground mb-1">{alias}</div>
        <div className="text-[10px] text-amber-400/80 animate-pulse">Initializing — waiting for drives...</div>
      </div>
    );
  }

  const servers = info.servers ?? [];
  const backend = info.backend ?? {};
  const usage = info.usage ?? {};
  const onlineDisks = backend.onlineDisks ?? 0;
  const offlineDisks = backend.offlineDisks ?? 0;
  const totalDisks = onlineDisks + offlineDisks;
  const usedBytes = usage.size ?? 0;
  const capacityBytes = usage.capacity ?? 0;

  // Extract version from first server
  const version = servers[0]?.version ?? null;

  return (
    <div className="mb-2 last:mb-0">
      {/* Cluster header */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-foreground">{alias}</span>
        <div className="flex items-center gap-1.5">
          {info.mode && (
            <span className="text-[9px] uppercase tracking-wider text-muted-foreground bg-muted/50 px-1 py-0.5 rounded">
              {info.mode}
            </span>
          )}
          {version && (
            <span className="text-[9px] text-muted-foreground font-mono">{version}</span>
          )}
        </div>
      </div>

      {/* Drive summary + capacity */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] mb-1.5">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Drives</span>
          <span className={`font-mono ${offlineDisks > 0 ? "text-orange-400" : "text-green-400"}`}>
            {onlineDisks}/{totalDisks} online
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Capacity</span>
          <span className="font-mono text-foreground">
            {formatBytes(usedBytes)} / {formatBytes(capacityBytes)}
          </span>
        </div>
      </div>

      {/* Per-server rows */}
      {servers.length > 0 && (
        <div className="space-y-0.5">
          {servers.map((server, idx) => {
            const hostname = server.endpoint
              ? server.endpoint.replace(/^https?:\/\//, "").replace(/:\d+$/, "")
              : `server-${idx}`;
            const drives = server.drives ?? [];
            const onlineDriveCount = drives.filter((d) => d.state === "ok").length;

            return (
              <div key={idx} className="flex items-center gap-1.5 text-[10px]">
                <span
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    server.state === "online" ? "bg-green-400" : "bg-red-400"
                  }`}
                />
                <span className="text-muted-foreground font-mono truncate flex-1">{hostname}</span>
                <div className="flex items-center gap-0.5 flex-shrink-0">
                  {drives.map((drive, dIdx) => (
                    <span
                      key={dIdx}
                      className={`w-1.5 h-1.5 rounded-sm ${
                        drive.state === "ok" ? "bg-green-400/70" : "bg-red-400/70"
                      }`}
                      title={`${drive.path ?? drive.endpoint ?? `disk-${dIdx}`}: ${drive.state}`}
                    />
                  ))}
                  {drives.length > 0 && (
                    <span className="text-muted-foreground ml-0.5">
                      {onlineDriveCount}/{drives.length}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---- Stats Tab ----

function StatsTabContent({
  data,
  isRunning,
  activeDemoId,
  clusters,
  clusterHealth,
}: {
  data: CockpitData | null;
  isRunning: boolean;
  activeDemoId: string | null;
  clusters: { id: string; drivesPerNode: number }[];
  clusterHealth: Record<string, string>;
}) {
  return (
    <>
      {!data || data.clusters.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          {!isRunning
            ? "Deploy a demo to see cockpit data"
            : (data as any)?.error
            ? (data as any).error
            : "Loading cluster data..."}
        </div>
      ) : (
        data.clusters.map((cluster) => {
          const totalObjects = cluster.buckets.reduce((sum, b) => sum + b.objects, 0);
          const rxRate = cluster.throughput.rx_bytes_per_sec || 0;
          const txRate = cluster.throughput.tx_bytes_per_sec || 0;

          return (
            <div key={cluster.alias} className="mb-3 last:mb-0">
              <div className="text-sm font-medium text-foreground mb-1">{cluster.alias}</div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
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

      {/* Cluster health panels — one per EC cluster */}
      {activeDemoId && isRunning && clusters.length > 0 && (
        <div className="mt-2 pt-2 border-t border-border">
          {clusters.map((cluster) => {
            const status = clusterHealth[cluster.id];
            return (
              <div key={cluster.id}>
                {status && (
                  <div className={`flex items-center gap-1.5 mb-1 px-1.5 py-0.5 rounded text-[11px] font-medium ${
                    status === "healthy"
                      ? "bg-green-500/10 text-green-400"
                      : status === "degraded"
                      ? "bg-orange-500/10 text-orange-400"
                      : "bg-red-500/10 text-red-400"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      status === "healthy" ? "bg-green-400" : status === "degraded" ? "bg-orange-400" : "bg-red-400"
                    }`} />
                    {cluster.id}: {status === "healthy" ? "quorum OK" : status === "degraded" ? "degraded — quorum lost" : "unreachable"}
                  </div>
                )}
                <ClusterHealthPanel
                  demoId={activeDemoId}
                  clusterId={cluster.id}
                  drivesPerNode={cluster.drivesPerNode}
                  overrideStatus={status as "healthy" | "degraded" | "unreachable" | undefined}
                />
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

// Re-export so App.tsx doesn't need to change the import
