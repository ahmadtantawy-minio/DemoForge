import { useEffect, useState, useRef, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { GripHorizontal, X, RefreshCw } from "lucide-react";
import ClusterHealthPanel from "./ClusterHealthPanel";
import { apiUrl } from "../../lib/apiBase";

interface BucketStat {
  name: string;
  objects: number;
  size: number;
}

interface ClusterStats {
  alias: string;
  buckets: BucketStat[];
  throughput: {
    rx_bytes_per_sec?: number;
    tx_bytes_per_sec?: number;
    put_ops_per_sec?: number;
    get_ops_per_sec?: number;
  };
  nginx_req_per_sec?: number;
  nginx_active_connections?: number;
  minio_rx_bytes_per_sec?: number;
  minio_tx_bytes_per_sec?: number;
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

function formatUptime(seconds: number): string {
  if (!seconds || seconds <= 0) return "";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  if (d > 0) return `${d}d ${h}h online`;
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m online`;
  return `${m}m online`;
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
  const [activeTab, setActiveTab] = useState<"health" | "stats" | "throughput">("health");
  const [clusters, setClusters] = useState<{ id: string; drivesPerNode: number }[]>([]);

  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isRunning = activeDemo?.status === "running";

  const toggleCockpit = useDemoStore((s) => s.toggleCockpit);

  const [refreshing, setRefreshing] = useState(false);

  // Declare fetch callbacks before effects so they're in scope
  const fetchCockpitNow = useCallback(async () => {
    if (!enabled || !activeDemoId || !isRunning) return;
    try {
      const res = await fetch(apiUrl(`/api/demos/${activeDemoId}/cockpit`));
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setData({ clusters: [], error: err.detail || `HTTP ${res.status}` } as any);
        return;
      }
      setData(await res.json());
    } catch { /* silently fail */ }
  }, [enabled, activeDemoId, isRunning]);

  const fetchHealthNow = useCallback(async () => {
    if (!enabled || !activeDemoId || !isRunning) return;
    try {
      const res = await fetch(apiUrl(`/api/demos/${activeDemoId}/cockpit/health`));
      if (!res.ok) return;
      setHealthData(await res.json());
    } catch { /* silently fail */ }
  }, [enabled, activeDemoId, isRunning]);

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    fetchCockpitNow();
    fetchHealthNow();
    setTimeout(() => setRefreshing(false), 800);
  }, [fetchCockpitNow, fetchHealthNow]);

  // Fetch full demo definition once when active demo changes to get cluster IDs
  useEffect(() => {
    if (!activeDemoId) {
      setClusters([]);
      return;
    }
    fetch(apiUrl(`/api/demos/${activeDemoId}`))
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
    fetchCockpitNow();
    const interval = setInterval(fetchCockpitNow, activeTab === "throughput" ? 1000 : 4000);
    return () => clearInterval(interval);
  }, [enabled, activeDemoId, isRunning, activeTab, fetchCockpitNow]);

  // Fetch health data (mc admin info) every 8 seconds
  useEffect(() => {
    if (!enabled || !activeDemoId || !isRunning) {
      setHealthData(null);
      return;
    }
    fetchHealthNow();
    const interval = setInterval(fetchHealthNow, 8000);
    return () => clearInterval(interval);
  }, [enabled, activeDemoId, isRunning, fetchHealthNow]);

  // Draggable position
  const [pos, setPos] = useState({ x: window.innerWidth - 420, y: 60 });
  const dragRef = useRef<{ startX: number; startY: number; posX: number; posY: number } | null>(null);

  // Resizable width and height
  const [cockpitWidth, setCockpitWidth] = useState(BASE_WIDTH);
  const [cockpitHeight, setCockpitHeight] = useState(() => Math.min(window.innerHeight * 0.6, 600));
  const resizeRef = useRef<{ startX: number; startWidth: number; startY: number; startHeight: number } | null>(null);

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
    resizeRef.current = { startX: e.clientX, startWidth: cockpitWidth, startY: e.clientY, startHeight: cockpitHeight };
    const onMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return;
      const newWidth = Math.max(280, Math.min(700, resizeRef.current.startWidth + (ev.clientX - resizeRef.current.startX)));
      const newHeight = Math.max(200, Math.min(window.innerHeight - 100, resizeRef.current.startHeight + (ev.clientY - resizeRef.current.startY)));
      setCockpitWidth(newWidth);
      setCockpitHeight(newHeight);
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [cockpitWidth, cockpitHeight]);

  const scale = cockpitWidth / BASE_WIDTH;

  return (
    <div
      className="fixed z-50 bg-card/95 backdrop-blur border border-border rounded-lg shadow-xl overflow-hidden flex flex-col"
      style={{ left: pos.x, top: pos.y, width: cockpitWidth }}
    >

      {/* Draggable header */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border cursor-move select-none"
        onMouseDown={onDragStart}
      >
        <div className="flex items-center gap-1.5">
          <GripHorizontal className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Cockpit</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-accent transition-colors"
            onClick={handleRefresh}
            title="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
          <button
            className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-accent transition-colors"
            onClick={toggleCockpit}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div
        className="flex border-b border-border bg-muted/30 select-none"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {(["health", "stats", "throughput"] as const).map((tab) => (
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

      {/* Scaled content wrapper — outer scrolls at cockpitHeight, inner scales content */}
      <div
        className="overflow-y-auto"
        style={{ height: cockpitHeight }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div
          style={{
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            width: BASE_WIDTH,
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
          ) : activeTab === "stats" ? (
            <StatsTabContent
              data={data}
              healthData={healthData}
              isRunning={isRunning}
              activeDemoId={activeDemoId}
              clusters={clusters}
              clusterHealth={clusterHealth}
            />
          ) : (
            <ThroughputTabContent
              data={data}
              healthData={healthData}
              isRunning={isRunning}
            />
          )}
        </div>
      </div>

      {/* Bottom-right corner resize handle */}
      <div
        className="absolute bottom-0 right-0 w-3 h-3 cursor-se-resize z-10 flex items-end justify-end pb-0.5 pr-0.5"
        onMouseDown={onResizeStart}
      >
        <svg width="8" height="8" viewBox="0 0 8 8" className="text-muted-foreground/50">
          <line x1="2" y1="8" x2="8" y2="2" stroke="currentColor" strokeWidth="1" />
          <line x1="5" y1="8" x2="8" y2="5" stroke="currentColor" strokeWidth="1" />
        </svg>
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

  const servers = [...(info.servers ?? [])].sort((a, b) => {
    const ha = (a.endpoint ?? "").replace(/^https?:\/\//, "").replace(/:\d+$/, "");
    const hb = (b.endpoint ?? "").replace(/^https?:\/\//, "").replace(/:\d+$/, "");
    return ha.localeCompare(hb, undefined, { numeric: true, sensitivity: "base" });
  });
  const backend = info.backend ?? {};
  const usage = info.usage ?? {};
  const onlineDisks = backend.onlineDisks ?? 0;
  const offlineDisks = backend.offlineDisks ?? 0;
  const totalDisks = onlineDisks + offlineDisks;
  const usedBytes = usage.size ?? 0;
  const capacityBytes = usage.capacity ?? 0;

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
          {servers[0]?.uptime ? (
            <span className="text-[9px] text-muted-foreground font-mono">{formatUptime(servers[0].uptime)}</span>
          ) : null}
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
  healthData,
  isRunning,
  activeDemoId,
  clusters,
  clusterHealth,
}: {
  data: CockpitData | null;
  healthData: CockpitHealthData | null;
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
                {(() => {
                  const clusterHealthInfo = healthData?.clusters?.find((c: any) => c.alias === cluster.alias);
                  const usedBytes = clusterHealthInfo?.info?.usage?.size ?? 0;
                  const capBytes = clusterHealthInfo?.info?.usage?.capacity ?? 0;
                  const pct = capBytes > 0 ? ((usedBytes / capBytes) * 100).toFixed(3) : null;
                  return (
                    <div className="col-span-2 mt-1 pt-1 border-t border-border/50">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-muted-foreground text-[10px]">{totalObjects.toLocaleString()} objects</span>
                        {capBytes > 0 && (
                          <span className="text-[10px] font-mono text-muted-foreground">
                            {formatBytes(usedBytes)} / {formatBytes(capBytes)}
                            {pct !== null && <span className="text-zinc-500 ml-1">· {pct}%</span>}
                          </span>
                        )}
                      </div>
                      {capBytes > 0 && (
                        <div className="mt-1 h-1 bg-zinc-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500/60 rounded-full"
                            style={{ width: `${Math.min(100, (usedBytes / capBytes) * 100)}%` }}
                          />
                        </div>
                      )}
                    </div>
                  );
                })()}
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
                    {cluster.id}: {status === "healthy" ? "quorum OK" : status === "degraded" ? "degraded" : "unreachable"}
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

// ---- Throughput Tab ----

function ThroughputTabContent({
  data,
  healthData,
  isRunning,
}: {
  data: CockpitData | null;
  healthData: CockpitHealthData | null;
  isRunning: boolean;
}) {
  if (!isRunning) {
    return <div className="text-xs text-muted-foreground">Start demo to see throughput</div>;
  }

  if (!data || data.clusters.length === 0) {
    return <div className="text-xs text-muted-foreground">No clusters running</div>;
  }

  return (
    <div className="space-y-3">
      {data.clusters.map((cluster) => {
        const healthStatus =
          healthData?.clusters.find((c) => c.alias === cluster.alias)?.status ?? "unreachable";
        const putOps = cluster.throughput.put_ops_per_sec ?? 0;
        const getOps = cluster.throughput.get_ops_per_sec ?? 0;
        const txRate = cluster.throughput.tx_bytes_per_sec ?? 0;
        const rxRate = cluster.throughput.rx_bytes_per_sec ?? 0;

        const healthColors: Record<string, string> = {
          healthy: "bg-green-500/10 text-green-400",
          degraded: "bg-orange-500/10 text-orange-400",
          starting: "bg-amber-500/10 text-amber-400",
          unreachable: "bg-red-500/10 text-red-400",
        };
        const dotColors: Record<string, string> = {
          healthy: "bg-green-400",
          degraded: "bg-orange-400",
          starting: "bg-amber-400",
          unreachable: "bg-red-400",
        };
        const colorClass = healthColors[healthStatus] ?? healthColors.unreachable;
        const dotClass = dotColors[healthStatus] ?? dotColors.unreachable;

        return (
          <div key={cluster.alias} className="mb-3 last:mb-0">
            {/* Cluster header with health badge */}
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-medium text-foreground">{cluster.alias}</span>
              <span className={`flex items-center gap-1 text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ${colorClass}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
                {healthStatus}
              </span>
            </div>

            {/* PUT / GET rows */}
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
              <div className="col-span-2 flex items-center gap-2">
                <span className="text-green-400">↑ PUT: {putOps.toFixed(0)} ops/s</span>
                {txRate > 0 && (
                  <span className="text-muted-foreground text-[10px]">({formatRate(txRate)})</span>
                )}
              </div>
              <div className="col-span-2 flex items-center gap-2">
                <span className="text-blue-400">↓ GET: {getOps.toFixed(0)} ops/s</span>
                {rxRate > 0 && (
                  <span className="text-muted-foreground text-[10px]">({formatRate(rxRate)})</span>
                )}
              </div>
            </div>

            {/* Nginx edge + MinIO direct sub-rows */}
            <div className="mt-1.5 pt-1.5 border-t border-border/40 space-y-0.5 text-[10px]">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Nginx (edge)</span>
                <span className="font-mono text-foreground">
                  {(cluster.nginx_req_per_sec ?? 0).toFixed(1)} req/s
                  <span className="text-muted-foreground ml-1">
                    ({cluster.nginx_active_connections ?? 0} active)
                  </span>
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">MinIO (cluster)</span>
                <span className="font-mono text-foreground">
                  ↑ {formatRate(cluster.minio_tx_bytes_per_sec ?? 0)}
                  <span className="text-muted-foreground mx-1">/</span>
                  ↓ {formatRate(cluster.minio_rx_bytes_per_sec ?? 0)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Re-export so App.tsx doesn't need to change the import
