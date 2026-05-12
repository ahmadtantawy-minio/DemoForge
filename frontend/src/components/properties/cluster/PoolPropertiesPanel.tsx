import { useEffect } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { MinioServerPool, DiskType } from "../../../types";
import {
  computeErasureSetSize,
  effectiveStripeSize,
  validStripeSizesForTotal,
  computePoolErasureStats,
  minioEcSettingOptions,
  clampParityToValidStripe,
  minioDefaultStandardParity,
  formatMinioEcStripeShort,
} from "../../../lib/erasure";

interface Props {
  pool: MinioServerPool;
  poolIndex: number;
  totalPools: number;
  onUpdate: (patch: Partial<MinioServerPool>) => void;
}

export default function PoolPropertiesPanel({ pool, poolIndex, totalPools, onUpdate }: Props) {
  const nodeCount = pool.nodeCount || 4;
  const drivesPerNode = pool.drivesPerNode || 4;
  const totalDrives = nodeCount * drivesPerNode;
  const stripeChoices = validStripeSizesForTotal(totalDrives);
  const setSize = effectiveStripeSize(totalDrives, pool.erasureStripeDrives ?? null);
  const numSets = totalDrives / setSize;
  const syncedParity = clampParityToValidStripe(
    setSize,
    pool.ecParity ?? minioDefaultStandardParity(setSize),
  );
  const stats = computePoolErasureStats(
    nodeCount,
    drivesPerNode,
    syncedParity,
    pool.diskSizeTb ?? 1,
    pool.erasureStripeDrives,
  );
  const ecOptions = minioEcSettingOptions(setSize);

  useEffect(() => {
    if (pool.ecParity !== syncedParity) {
      onUpdate({ ecParity: syncedParity });
    }
  }, [syncedParity, pool.ecParity, onUpdate]);

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
            const newNodeCount = parseInt(v, 10);
            const minDrives = newNodeCount === 2 ? 2 : 1;
            const newDrivesPerNode = Math.max(drivesPerNode, minDrives);
            const newTotal = newNodeCount * newDrivesPerNode;
            const keepStripe =
              pool.erasureStripeDrives != null &&
              pool.erasureStripeDrives > 0 &&
              newTotal % pool.erasureStripeDrives === 0;
            const stripeForParity = effectiveStripeSize(
              newTotal,
              keepStripe ? pool.erasureStripeDrives : null,
            );
            const newParity = clampParityToValidStripe(
              stripeForParity,
              pool.ecParity ?? minioDefaultStandardParity(stripeForParity),
            );
            const patch: Partial<MinioServerPool> = { nodeCount: newNodeCount, ecParity: newParity };
            if (newDrivesPerNode !== drivesPerNode) patch.drivesPerNode = newDrivesPerNode;
            if (!keepStripe) patch.erasureStripeDrives = null;
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
            const newDrivesPerNode = parseInt(v, 10);
            const newTotal = nodeCount * newDrivesPerNode;
            const keepStripe =
              pool.erasureStripeDrives != null &&
              pool.erasureStripeDrives > 0 &&
              newTotal % pool.erasureStripeDrives === 0;
            const stripeForParity = effectiveStripeSize(
              newTotal,
              keepStripe ? pool.erasureStripeDrives : null,
            );
            const newParity = clampParityToValidStripe(
              stripeForParity,
              pool.ecParity ?? minioDefaultStandardParity(stripeForParity),
            );
            const patch: Partial<MinioServerPool> = { drivesPerNode: newDrivesPerNode, ecParity: newParity };
            if (!keepStripe) patch.erasureStripeDrives = null;
            onUpdate(patch);
          }}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
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
          {totalDrives} total drives →{" "}
          <span className="font-medium text-foreground">
            {numSets} × {setSize}-drive erasure set{numSets > 1 ? "s" : ""}
          </span>
          . Each set uses the same EC ratio below.
        </p>
      </div>

      {stripeChoices.length > 1 && (
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Erasure stripe width</label>
          <Select
            value={pool.erasureStripeDrives == null ? "auto" : String(pool.erasureStripeDrives)}
            onValueChange={(v) => {
              if (v === "auto") {
                const autoS = computeErasureSetSize(totalDrives);
                onUpdate({
                  erasureStripeDrives: null,
                  ecParity: clampParityToValidStripe(
                    autoS,
                    pool.ecParity ?? minioDefaultStandardParity(autoS),
                  ),
                });
                return;
              }
              const w = parseInt(v, 10);
              const newParity = clampParityToValidStripe(
                w,
                pool.ecParity ?? minioDefaultStandardParity(w),
              );
              onUpdate({ erasureStripeDrives: w, ecParity: newParity });
            }}
          >
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">
                Auto ({computeErasureSetSize(totalDrives)} drives/set — default layout)
              </SelectItem>
              {stripeChoices.map((w) => (
                <SelectItem key={w} value={String(w)}>
                  {w} drives/set → {totalDrives / w} erasure set{totalDrives / w > 1 ? "s" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            Same total drives can form one wide stripe or more smaller stripes (e.g. 16 disks → 16 or 8+8). EC options
            below follow the stripe width you pick.
          </p>
        </div>
      )}

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
          value={String(pool.diskSizeTb ?? 1)}
          onValueChange={(v) => onUpdate({ diskSizeTb: parseInt(v) })}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[1, 2, 4, 8, 16, 32].map((n) => (
              <SelectItem key={n} value={String(n)}>
                {n} TB
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          Simulated disk capacity for planning display only. Does not affect containers.
        </p>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">EC setting (STANDARD class)</label>
        {ecOptions.length === 0 ? (
          <p className="text-xs text-destructive leading-snug">
            No valid MinIO STANDARD layout for this pool: each erasure stripe needs at least 4 drives with parity
            between 2 and half the stripe size. Increase nodes or drives per node.
          </p>
        ) : (
          <Select
            value={String(syncedParity)}
            onValueChange={(v) => onUpdate({ ecParity: parseInt(v, 10) })}
          >
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue>{formatMinioEcStripeShort(setSize, syncedParity)}</SelectValue>
            </SelectTrigger>
            <SelectContent className="max-w-[min(100vw-2rem,28rem)]">
              {ecOptions.map((opt) => (
                <SelectItem key={opt.value} value={String(opt.value)} textValue={opt.shortLabel}>
                  <div className="flex flex-col gap-0.5 py-0.5">
                    <span className="font-mono text-xs">{opt.shortLabel}</span>
                    <span className="text-[10px] text-muted-foreground leading-snug">{opt.label}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <p className="text-[10px] text-muted-foreground mt-0.5">
          <span className="font-mono">EC &lt;stripe&gt;:&lt;parity&gt;</span>: drives in one erasure set vs parity shards.
          Deploy sets <span className="font-mono">MINIO_STORAGE_CLASS_STANDARD=EC:{syncedParity}</span> (parity count only, MinIO syntax).
        </p>
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
        <p className="text-[10px] text-muted-foreground mt-0.5">
          upgrade: auto-increase parity when drives are offline. ignore: keep configured parity.
        </p>
      </div>

      <div className="mt-3 pt-3 border-t border-border space-y-1.5">
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-2">
          Pool capacity &amp; resilience
        </p>
        {[
          ["EC (this pool)", formatMinioEcStripeShort(setSize, syncedParity)],
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
