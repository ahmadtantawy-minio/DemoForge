import ComponentIcon from "../../../shared/ComponentIcon";
import type { MinioServerPool, ContainerInstance } from "../../../../types";
import type { computeClusterAggregates } from "../../../../lib/clusterUtils";
import { computeClusterDriveHealth } from "../../../../lib/clusterUtils";

interface Props {
  label: string;
  clusterId: string;
  pools: MinioServerPool[];
  aggregates: ReturnType<typeof computeClusterAggregates>;
  clusterInstances: ContainerInstance[];
  clusterStatus: string | null;
}

export default function ClusterHeader({
  label,
  clusterId,
  pools,
  aggregates,
  clusterInstances,
  clusterStatus,
}: Props) {
  const { drivesOnline, drivesTotal, nodesUp, nodesTotal } = computeClusterDriveHealth(
    pools,
    clusterInstances,
    clusterId,
  );

  let subtitle: string;
  if (pools.length === 1) {
    const pool = pools[0];
    subtitle = `${pool.nodeCount} nodes × ${pool.drivesPerNode} drives · ${aggregates.ecSummary} · ${aggregates.totalUsableTb} TB usable`;
  } else {
    subtitle = `${pools.length} pools · ${aggregates.totalNodes} nodes · ${aggregates.totalDrives} drives · ${aggregates.totalUsableTb} TB usable`;
  }

  return (
    <div className="flex items-center gap-2 mb-2">
      <div
        className="flex items-center justify-center"
        style={{ width: 34, height: 34, background: "#1d1d1d", borderRadius: 7 }}
      >
        <ComponentIcon icon="minio" size={22} className="text-[#C72C48]" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sm text-foreground truncate">{label}</div>
        <div className="text-[11px] text-zinc-400" style={{ whiteSpace: "nowrap" }}>{subtitle}</div>
      </div>
      <div className="flex flex-col items-end gap-0.5">
        {clusterInstances.length > 0 && (
          <div
            className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
              drivesOnline === drivesTotal && nodesUp === nodesTotal
                ? "bg-green-500/15 text-green-400"
                : drivesOnline > 0
                ? "bg-yellow-500/15 text-yellow-400"
                : "bg-red-500/15 text-red-400"
            }`}
            title={`${drivesOnline}/${drivesTotal} drives online · ${nodesUp}/${nodesTotal} nodes up`}
          >
            {drivesOnline}/{drivesTotal}
          </div>
        )}
        {clusterStatus && (() => {
          const isHealthy = clusterStatus === "healthy";
          const isDegraded = clusterStatus === "degraded";
          const isQuorumLost = clusterStatus === "quorum_lost";
          const isUnreachable = clusterStatus === "unreachable";
          const badgeColor = isHealthy
            ? "bg-green-500/15 text-green-400"
            : isDegraded
            ? "bg-orange-500/15 text-orange-400"
            : isUnreachable
            ? "bg-zinc-500/15 text-zinc-400"
            : "bg-red-500/15 text-red-400";
          const dotColor = isHealthy
            ? "bg-green-400"
            : isDegraded
            ? "bg-orange-400"
            : isUnreachable
            ? "bg-zinc-400"
            : "bg-red-400";
          const label = isHealthy
            ? "healthy"
            : isDegraded
            ? "degraded"
            : isQuorumLost
            ? "no quorum"
            : isUnreachable
            ? "unreachable"
            : clusterStatus;
          return (
            <div className={`text-[9px] font-medium px-1.5 py-0.5 rounded flex items-center gap-1 ${badgeColor}`}>
              <span className={`w-1.5 h-1.5 rounded-full inline-block ${dotColor}`} />
              {label}
            </div>
          );
        })()}
      </div>
    </div>
  );
}
