import { useEffect, useState, useRef } from "react";
import { apiUrl } from "../../lib/apiBase";

interface DriveInfo {
  path: string;
  state: "ok" | "offline" | "healing" | string;
  used: number;
  total: number;
}

interface ServerInfo {
  endpoint: string;
  state: string;
  uptime: number;
  drives: DriveInfo[];
  network: { online: number; total: number };
}

interface ClusterHealth {
  cluster_id: string;
  ec_parity: number;
  servers: ServerInfo[];
  drives_online: number;
  drives_total: number;
  erasure_sets: number;
  status: "healthy" | "degraded" | "quorum_lost" | "unknown";
  error?: string;
}

interface HealingStatus {
  active: boolean;
  objects_total?: number;
  objects_healed?: number;
  objects_remaining?: number;
}

interface Props {
  demoId: string;
  clusterId: string;
  drivesPerNode?: number;
  overrideStatus?: "healthy" | "degraded" | "unreachable";
}

// Pending confirmation state for a simulated action
interface PendingConfirm {
  type: "drive" | "node";
  node: string;
  drive?: string;
  warning: string;
}

function hostnameFromEndpoint(endpoint: string): string {
  try {
    const url = new URL(endpoint.startsWith("http") ? endpoint : `http://${endpoint}`);
    return url.hostname;
  } catch {
    return endpoint.split(":")[0] || endpoint;
  }
}

// Extract node alias from endpoint hostname, e.g. "minio-mycluster1" -> "minio1"
// Container DNS names follow the alias_prefix pattern from compose_generator:
// alias_prefix = f"minio-{cluster.id.replace('-', '')}" and alias = f"{alias_prefix}{i}"
// So "minio-mycluster1" maps to node index 1 -> "node-1"
function nodeIndexFromHostname(hostname: string, clusterId: string): string {
  const prefix = `minio-${clusterId.replace(/-/g, "")}`;
  if (hostname.startsWith(prefix)) {
    const idx = hostname.slice(prefix.length);
    return `node-${idx}`;
  }
  // fallback: try to extract trailing digit
  const m = hostname.match(/(\d+)$/);
  return m ? `node-${m[1]}` : hostname;
}

function DriveIndicator({ state }: { state: string }) {
  const color =
    state === "ok"
      ? "bg-green-500"
      : state === "healing"
      ? "bg-amber-400"
      : "bg-red-500";
  const title = state === "ok" ? "Online" : state === "healing" ? "Healing" : "Offline";
  return (
    <div
      className={`w-2.5 h-2.5 rounded-full ${color} flex-shrink-0`}
      title={title}
    />
  );
}

export default function ClusterHealthPanel({ demoId, clusterId, drivesPerNode = 4, overrideStatus }: Props) {
  const [health, setHealth] = useState<ClusterHealth | null>(null);
  const [healing, setHealing] = useState<HealingStatus | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Simulation state
  const [simulatedDrives, setSimulatedDrives] = useState<Set<string>>(new Set()); // "node-1/data3"
  const [simulatedNodes, setSimulatedNodes] = useState<Set<string>>(new Set());   // "node-1"
  const [simulating, setSimulating] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  // Which node's drive picker is open
  const [drivePickerNode, setDrivePickerNode] = useState<string | null>(null);

  const refreshHealth = async () => {
    try {
      const [hRes, healRes] = await Promise.all([
        fetch(apiUrl(`/api/demos/${demoId}/clusters/${clusterId}/health`)),
        fetch(apiUrl(`/api/demos/${demoId}/clusters/${clusterId}/healing`)),
      ]);
      if (hRes.ok) {
        const data: ClusterHealth = await hRes.json();
        setHealth(data);
      }
      if (healRes.ok) {
        const data: HealingStatus = await healRes.json();
        setHealing(data);
      }
    } catch {
      // silently ignore — non-critical
    }
  };

  useEffect(() => {
    refreshHealth();
    intervalRef.current = setInterval(refreshHealth, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [demoId, clusterId]);

  // Close drive picker on outside click
  useEffect(() => {
    if (!drivePickerNode) return;
    const handler = () => setDrivePickerNode(null);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [drivePickerNode]);

  const postSimulate = async (endpoint: string, body: Record<string, unknown>) => {
    const res = await fetch(
      apiUrl(`/api/demos/${demoId}/clusters/${clusterId}/simulate/${endpoint}`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
    return res.json();
  };

  const handleFailDrive = async (nodeKey: string, drive: string, force = false) => {
    setSimulating(`${nodeKey}/${drive}`);
    setDrivePickerNode(null);
    try {
      const data = await postSimulate("fail-drive", { node: nodeKey, drive, force });
      if (data.warning && !force) {
        setPendingConfirm({ type: "drive", node: nodeKey, drive, warning: data.warning });
        return;
      }
      if (data.status === "drive_failed") {
        setSimulatedDrives((prev) => new Set(prev).add(`${nodeKey}/${drive}`));
        await refreshHealth();
      }
    } finally {
      setSimulating(null);
    }
  };

  const handleRestoreDrive = async (nodeKey: string, drive: string) => {
    setSimulating(`restore-${nodeKey}/${drive}`);
    try {
      const data = await postSimulate("restore-drive", { node: nodeKey, drive });
      if (data.status === "drive_restored") {
        setSimulatedDrives((prev) => {
          const next = new Set(prev);
          next.delete(`${nodeKey}/${drive}`);
          return next;
        });
        await refreshHealth();
      }
    } finally {
      setSimulating(null);
    }
  };

  const handleFailNode = async (nodeKey: string, force = false) => {
    setSimulating(`node-${nodeKey}`);
    try {
      const data = await postSimulate("fail-node", { node: nodeKey, force });
      if (data.warning && !force) {
        setPendingConfirm({ type: "node", node: nodeKey, warning: data.warning });
        return;
      }
      if (data.status === "node_stopped") {
        setSimulatedNodes((prev) => new Set(prev).add(nodeKey));
        await refreshHealth();
      }
    } finally {
      setSimulating(null);
    }
  };

  const handleRestoreNode = async (nodeKey: string) => {
    setSimulating(`restore-node-${nodeKey}`);
    try {
      const data = await postSimulate("restore-node", { node: nodeKey });
      if (data.status === "node_started") {
        setSimulatedNodes((prev) => {
          const next = new Set(prev);
          next.delete(nodeKey);
          return next;
        });
        await refreshHealth();
      }
    } finally {
      setSimulating(null);
    }
  };

  const handleRestoreAll = async () => {
    setSimulating("restore-all");
    try {
      await postSimulate("restore-all", {});
      setSimulatedDrives(new Set());
      setSimulatedNodes(new Set());
      await refreshHealth();
    } finally {
      setSimulating(null);
    }
  };

  const handleConfirmProceed = async () => {
    if (!pendingConfirm) return;
    const { type, node, drive } = pendingConfirm;
    setPendingConfirm(null);
    if (type === "drive" && drive) {
      await handleFailDrive(node, drive, true);
    } else if (type === "node") {
      await handleFailNode(node, true);
    }
  };

  if (!health) return null;

  // Polling /minio/health/cluster is authoritative for quorum — override mc admin info when they disagree
  const effectiveStatus: typeof health.status =
    overrideStatus === "degraded" || overrideStatus === "unreachable"
      ? "quorum_lost"
      : health.status;

  const statusColor =
    effectiveStatus === "healthy"
      ? "text-green-400"
      : effectiveStatus === "degraded"
      ? "text-amber-400"
      : effectiveStatus === "quorum_lost"
      ? "text-red-400"
      : "text-zinc-400";

  const statusLabel =
    effectiveStatus === "healthy"
      ? "Healthy"
      : effectiveStatus === "degraded"
      ? "Degraded"
      : effectiveStatus === "quorum_lost"
      ? "Write quorum lost"
      : "Unknown";

  const driveCountColor =
    health.drives_online === health.drives_total && health.drives_total > 0 && effectiveStatus === "healthy"
      ? "text-green-400"
      : effectiveStatus === "quorum_lost"
      ? "text-red-400"
      : "text-amber-400";

  const hasSimulations = simulatedDrives.size > 0 || simulatedNodes.size > 0;

  // Error / unavailable state
  if (health.error || health.status === "unknown") {
    return (
      <div className="mb-3 last:mb-0">
        <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
          Cluster Health
        </div>
        <div className="text-[10px] text-muted-foreground italic">
          Health data unavailable — cluster may be starting
        </div>
      </div>
    );
  }

  const driveLabels = Array.from({ length: drivesPerNode }, (_, i) => `data${i + 1}`);

  return (
    <div className="mb-3 last:mb-0">
      {/* Header bar */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          Cluster Health
        </div>
        <div className="flex items-center gap-2">
          {/* Restore all button — only shown when simulations active */}
          {hasSimulations && (
            <button
              onClick={handleRestoreAll}
              disabled={simulating === "restore-all"}
              className="text-[10px] px-1.5 py-0.5 rounded border border-green-900/50 text-green-400 hover:bg-green-900/20 disabled:opacity-50"
            >
              {simulating === "restore-all" ? "Restoring…" : "Restore all"}
            </button>
          )}
          {/* EC badge */}
          <span className="text-[9px] font-mono bg-green-500/20 text-green-400 border border-green-500/30 rounded px-1 py-0.5">
            EC:{health.ec_parity}
          </span>
          {/* Drive count */}
          <span className={`text-[9px] font-mono ${driveCountColor}`}>
            {health.drives_online}/{health.drives_total}
          </span>
          {/* Status */}
          <span className={`text-[9px] font-medium ${statusColor}`}>
            {statusLabel}
          </span>
        </div>
      </div>

      {/* Pending warning confirmation */}
      {pendingConfirm && (
        <div className="mb-1.5 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5">
          <div className="text-[9px] font-semibold text-amber-400 mb-1">Quorum warning</div>
          <div className="text-[9px] text-amber-300 mb-1.5">{pendingConfirm.warning}</div>
          <div className="flex gap-1.5">
            <button
              onClick={handleConfirmProceed}
              className="text-[10px] px-1.5 py-0.5 rounded border border-red-900/50 text-red-400 hover:bg-red-900/20"
            >
              Proceed anyway
            </button>
            <button
              onClick={() => setPendingConfirm(null)}
              className="text-[10px] px-1.5 py-0.5 rounded border border-zinc-700 text-zinc-400 hover:bg-zinc-700/40"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Node cards */}
      {health.servers.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-1.5">
          {health.servers.map((srv, idx) => {
            const host = hostnameFromEndpoint(srv.endpoint);
            const nodeKey = nodeIndexFromHostname(host, clusterId);
            const isOffline = srv.state !== "online";
            const nodeSimulated = simulatedNodes.has(nodeKey);

            return (
              <div
                key={idx}
                className={`rounded border px-1.5 py-1 min-w-0 flex-1 basis-[calc(50%-3px)] ${
                  nodeSimulated
                    ? "border-red-500/60 bg-red-500/15"
                    : isOffline
                    ? "border-red-500/40 bg-red-500/10"
                    : "border-zinc-700 bg-zinc-800/60"
                }`}
              >
                {/* Node hostname + node-level controls */}
                <div className="flex items-center justify-between gap-1 mb-1">
                  <div
                    className={`text-[9px] font-mono truncate ${
                      isOffline || nodeSimulated ? "text-red-400" : "text-zinc-300"
                    }`}
                    title={srv.endpoint}
                  >
                    {host}
                  </div>
                  {/* Node fail / restore button */}
                  {nodeSimulated ? (
                    <button
                      onClick={() => handleRestoreNode(nodeKey)}
                      disabled={simulating === `restore-node-${nodeKey}`}
                      className="text-[10px] px-1.5 py-0.5 rounded border border-green-900/50 text-green-400 hover:bg-green-900/20 disabled:opacity-50 flex-shrink-0"
                    >
                      Restore
                    </button>
                  ) : (
                    <button
                      onClick={() => handleFailNode(nodeKey)}
                      disabled={!!simulating}
                      className="text-[10px] px-1.5 py-0.5 rounded border border-red-900/50 text-red-400 hover:bg-red-900/20 disabled:opacity-50 flex-shrink-0"
                    >
                      Fail
                    </button>
                  )}
                </div>

                {/* Drive indicators */}
                <div className="flex flex-wrap gap-0.5 mb-1">
                  {srv.drives.map((d, di) => (
                    <DriveIndicator key={di} state={d.state} />
                  ))}
                </div>

                {/* Drive simulation controls */}
                <div className="flex flex-wrap gap-0.5">
                  {driveLabels.map((driveLabel) => {
                    const key = `${nodeKey}/${driveLabel}`;
                    const isFailed = simulatedDrives.has(key);
                    const isLoading =
                      simulating === key || simulating === `restore-${key}`;
                    return isFailed ? (
                      <button
                        key={driveLabel}
                        onClick={() => handleRestoreDrive(nodeKey, driveLabel)}
                        disabled={isLoading}
                        className="text-[10px] px-1 py-0 rounded border border-green-900/50 text-green-400 hover:bg-green-900/20 disabled:opacity-50 leading-4"
                        title={`Restore ${driveLabel}`}
                      >
                        {driveLabel}↑
                      </button>
                    ) : (
                      <button
                        key={driveLabel}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleFailDrive(nodeKey, driveLabel);
                        }}
                        disabled={isLoading || nodeSimulated}
                        className="text-[10px] px-1 py-0 rounded border border-red-900/30 text-red-400/70 hover:bg-red-900/20 hover:text-red-400 disabled:opacity-30 leading-4"
                        title={`Fail ${driveLabel}`}
                      >
                        {driveLabel}
                      </button>
                    );
                  })}
                </div>

                {/* Peer count */}
                {srv.network.total > 0 && (
                  <div className="text-[8px] text-zinc-500 mt-0.5">
                    {srv.network.online}/{srv.network.total} peers
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Healing panel — only when active */}
      {healing?.active && (
        <div className="mt-1 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1">
          <div className="text-[9px] font-semibold text-amber-400 mb-0.5">Healing in progress</div>
          <div className="text-[9px] text-amber-300 font-mono">
            {(healing.objects_healed ?? 0).toLocaleString()} / {(healing.objects_total ?? 0).toLocaleString()} objects
            {(healing.objects_remaining ?? 0) > 0 && (
              <span className="text-zinc-400"> ({(healing.objects_remaining ?? 0).toLocaleString()} remaining)</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
