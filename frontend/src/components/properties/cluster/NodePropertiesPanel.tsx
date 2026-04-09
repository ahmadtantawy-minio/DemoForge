import type { ContainerInstance } from "../../../types";
import DriveCell from "../../canvas/nodes/cluster/DriveCell";
import { proxyUrl } from "../../../api/client";

interface Props {
  nodeId: string; // container name e.g. "cluster-1-node-2" or "cluster-1-pool2-node-1"
  poolId: string;
  nodeIndex: number;
  instance: ContainerInstance | undefined;
  drivesPerNode: number;
  isRunning: boolean;
}

function healthBadgeClass(health: string): string {
  switch (health) {
    case "healthy":
      return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
    case "starting":
      return "bg-amber-500/15 text-amber-400 border-amber-500/30";
    case "degraded":
      return "bg-orange-500/15 text-orange-400 border-orange-500/30";
    case "stopped":
      return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
    case "error":
      return "bg-red-500/15 text-red-400 border-red-500/30";
    default:
      return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  }
}

function driveStatus(
  instance: ContainerInstance | undefined,
  driveNum: number,
  isRunning: boolean
): "healthy" | "failed" | "healing" | "offline" {
  if (!isRunning || !instance) return "offline";
  if (instance.health === "stopped") return "offline";
  if (instance.stopped_drives?.includes(driveNum)) return "failed";
  if (instance.health === "healthy") return "healthy";
  if (instance.health === "starting") return "healing";
  if (instance.health === "degraded") return "healing";
  return "offline";
}

export default function NodePropertiesPanel({ nodeId, poolId, nodeIndex, instance, drivesPerNode, isRunning }: Props) {
  const poolMatch = poolId.match(/pool-?(\d+)/i);
  const poolLabel = poolMatch ? `Pool ${poolMatch[1]}` : poolId;
  const status = isRunning ? (instance?.health ?? "offline") : "offline";

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Node {nodeIndex} <span className="text-muted-foreground/70">— {poolLabel}</span>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Container</label>
        <div className="text-xs font-mono bg-muted px-1.5 py-1 rounded break-all">{nodeId}</div>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Status</label>
        <span className={`text-[10px] px-2 py-0.5 rounded border inline-block ${healthBadgeClass(status)}`}>
          {status}
        </span>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">
          Drives <span className="text-muted-foreground/70">({drivesPerNode})</span>
        </label>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 3,
            padding: 4,
            borderRadius: 4,
            border: "0.5px solid rgba(212,212,216,0.2)",
            background: "rgba(244,244,245,0.5)",
            width: 96,
          }}
        >
          {Array.from({ length: drivesPerNode }, (_, d) => (
            <DriveCell
              key={d}
              status={driveStatus(instance, d + 1, isRunning)}
              onContextMenu={(e) => e.preventDefault()}
            />
          ))}
        </div>
        {instance?.stopped_drives && instance.stopped_drives.length > 0 && (
          <p className="text-[10px] text-muted-foreground mt-1">
            Stopped drives: {instance.stopped_drives.join(", ")}
          </p>
        )}
      </div>

      {instance && instance.web_uis.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="text-xs text-muted-foreground mb-1">Web UIs</div>
          {instance.web_uis.map((ui) => (
            <a
              key={ui.name}
              href={proxyUrl(ui.proxy_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-xs text-primary hover:underline mb-1"
            >
              {ui.name}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
