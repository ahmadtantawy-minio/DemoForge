import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { MinioServerPool, DiskType } from "../../../types";
import { computeErasureSetSize, computeECOptions, computePoolErasureStats } from "../../../lib/erasure";

interface Props {
  pool: MinioServerPool;
  poolIndex: number;
  totalPools: number;
  onUpdate: (patch: Partial<MinioServerPool>) => void;
}

export default function PoolPropertiesPanel({ pool, poolIndex, totalPools, onUpdate }: Props) {
  const nodeCount = pool.nodeCount || 4;
  const drivesPerNode = pool.drivesPerNode || 1;
  const totalDrives = nodeCount * drivesPerNode;
  const setSize = computeErasureSetSize(totalDrives);
  const numSets = totalDrives / setSize;
  const stats = computePoolErasureStats(nodeCount, drivesPerNode, pool.ecParity ?? 4, pool.diskSizeTb ?? 8);

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Pool {poolIndex}
        <span className="ml-1 text-[10px] normal-case text-muted-foreground/70">of {totalPools}</span>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Node Count</label>
        <Select
          value={String(nodeCount)}
          onValueChange={(v) => {
            const newNodeCount = parseInt(v);
            // 2-node pools need at least 2 drives to meet the 4-drive minimum
            const minDrives = newNodeCount === 2 ? 2 : 1;
            const newDrivesPerNode = Math.max(drivesPerNode, minDrives);
            const newTotal = newNodeCount * newDrivesPerNode;
            const newSetSize = computeErasureSetSize(newTotal);
            const maxParity = Math.floor(newSetSize / 2);
            const defaultParity = newSetSize <= 5 ? 2 : newSetSize <= 7 ? 3 : 4;
            const currentParity = pool.ecParity ?? 4;
            const patch: Partial<MinioServerPool> = { nodeCount: newNodeCount };
            if (newDrivesPerNode !== drivesPerNode) patch.drivesPerNode = newDrivesPerNode;
            if (currentParity > maxParity) patch.ecParity = defaultParity;
            onUpdate(patch);
          }}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="2">2 nodes</SelectItem>
            <SelectItem value="4">4 nodes</SelectItem>
            <SelectItem value="6">6 nodes</SelectItem>
            <SelectItem value="8">8 nodes</SelectItem>
            <SelectItem value="16">16 nodes</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Drives per Node</label>
        <Select
          value={String(drivesPerNode)}
          onValueChange={(v) => {
            const newDrivesPerNode = parseInt(v);
            const newTotal = nodeCount * newDrivesPerNode;
            const newSetSize = computeErasureSetSize(newTotal);
            const maxParity = Math.floor(newSetSize / 2);
            const defaultParity = newSetSize <= 5 ? 2 : newSetSize <= 7 ? 3 : 4;
            const currentParity = pool.ecParity ?? 4;
            if (currentParity > maxParity) {
              onUpdate({ drivesPerNode: newDrivesPerNode, ecParity: defaultParity });
            } else {
              onUpdate({ drivesPerNode: newDrivesPerNode });
            }
          }}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {/* 2-node pools need ≥2 drives/node to meet the 4-drive EC minimum */}
            {nodeCount > 2 && <SelectItem value="1">1 drive</SelectItem>}
            <SelectItem value="2">2 drives</SelectItem>
            <SelectItem value="4">4 drives</SelectItem>
            <SelectItem value="6">6 drives</SelectItem>
            <SelectItem value="8">8 drives</SelectItem>
            <SelectItem value="12">12 drives</SelectItem>
            <SelectItem value="16">16 drives</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          {totalDrives} total drives → <span className="font-medium text-foreground">{numSets} × {setSize}-drive erasure set{numSets > 1 ? "s" : ""}</span>
        </p>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Disk Type</label>
        <Select
          value={pool.diskType || "ssd"}
          onValueChange={(v) => onUpdate({ diskType: v as DiskType })}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="nvme">NVMe SSD</SelectItem>
            <SelectItem value="ssd">SSD</SelectItem>
            <SelectItem value="hdd">HDD</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-0.5">Display only — for demo storytelling</p>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Disk size per node</label>
        <Select
          value={String(pool.diskSizeTb ?? 8)}
          onValueChange={(v) => onUpdate({ diskSizeTb: parseInt(v) })}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[1, 2, 4, 8, 16, 32].map((n) => (
              <SelectItem key={n} value={String(n)}>{n} TB</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-0.5">Simulated disk capacity for planning display only. Does not affect containers.</p>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">EC parity</label>
        <Select
          value={String(pool.ecParity ?? 4)}
          onValueChange={(v) => onUpdate({ ecParity: parseInt(v) })}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {computeECOptions(setSize).map((opt) => (
              <SelectItem key={opt.value} value={String(opt.value)}>{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-0.5">Number of parity shards per erasure set. Higher = more fault tolerance, less usable capacity.</p>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Parity upgrade policy</label>
        <Select
          value={pool.ecParityUpgradePolicy ?? "upgrade"}
          onValueChange={(v) => onUpdate({ ecParityUpgradePolicy: v })}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="upgrade">upgrade</SelectItem>
            <SelectItem value="ignore">ignore</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-0.5">upgrade: auto-increase parity when drives are offline. ignore: keep configured parity.</p>
      </div>

      {/* Pool-scoped Capacity & resilience info card */}
      <div className="mt-3 pt-3 border-t border-border space-y-1.5">
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-2">Pool capacity &amp; resilience</p>
        {[
          ["Erasure sets", `${stats.numSets} × ${stats.setSize} drives`],
          ["Usable ratio", `${Math.round(stats.usableRatio * 100)}% (${stats.dataShards} data + ${stats.parityShards} parity)`],
          ["Raw capacity", `${stats.rawTb} TB`],
          ["Usable capacity", `${stats.usableTb} TB`],
          ["Drive tolerance", `${stats.driveTolerance} per erasure set`],
          ["Read quorum", `${stats.readQuorum} drives`],
          ["Write quorum", `${stats.writeQuorum} drives`],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">{label}</span>
            <span className="text-[11px] text-foreground font-mono">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
