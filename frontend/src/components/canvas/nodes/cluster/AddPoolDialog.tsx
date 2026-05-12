import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import type { MinioServerPool, DiskType } from "../../../../types";
import {
  computeErasureSetSize,
  effectiveStripeSize,
  validStripeSizesForTotal,
  computePoolErasureStats,
  minioEcSettingOptions,
  clampParityToValidStripe,
  minioDefaultStandardParity,
  formatMinioEcStripeShort,
} from "../../../../lib/erasure";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Row to copy defaults from (last pool or pool being duplicated). */
  templatePool: MinioServerPool;
  /** Assigned id for the new row, e.g. pool-2 */
  nextPoolId: string;
  isRunning: boolean;
  title: string;
  onConfirm: (pool: MinioServerPool) => void | Promise<void>;
}

export default function AddPoolDialog({
  open,
  onOpenChange,
  templatePool,
  nextPoolId,
  isRunning,
  title,
  onConfirm,
}: Props) {
  const [nodeCount, setNodeCount] = useState(4);
  const [drivesPerNode, setDrivesPerNode] = useState(4);
  const [diskType, setDiskType] = useState<DiskType>("ssd");
  const [diskSizeTb, setDiskSizeTb] = useState(1);
  const [ecParity, setEcParity] = useState(3);
  const [ecParityUpgradePolicy, setEcParityUpgradePolicy] = useState("upgrade");
  const [erasureStripeDrives, setErasureStripeDrives] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const t = templatePool;
    setNodeCount(t.nodeCount ?? 4);
    setDrivesPerNode(t.drivesPerNode ?? 4);
    setDiskType((t.diskType as DiskType) || "ssd");
    setDiskSizeTb(t.diskSizeTb ?? 1);
    setEcParity(t.ecParity ?? 3);
    setEcParityUpgradePolicy(t.ecParityUpgradePolicy ?? "upgrade");
    setErasureStripeDrives(t.erasureStripeDrives ?? null);
  }, [open, templatePool]);

  const totalDrives = nodeCount * drivesPerNode;
  const stripeChoices = validStripeSizesForTotal(totalDrives);
  const setSize = effectiveStripeSize(totalDrives, erasureStripeDrives);
  const numSets = totalDrives / setSize;
  const syncedParity = clampParityToValidStripe(
    setSize,
    ecParity ?? minioDefaultStandardParity(setSize),
  );
  const stats = computePoolErasureStats(nodeCount, drivesPerNode, syncedParity, diskSizeTb, erasureStripeDrives);
  const ecOptions = minioEcSettingOptions(setSize);

  useEffect(() => {
    if (ecParity !== syncedParity) setEcParity(syncedParity);
  }, [syncedParity, ecParity]);

  const buildPool = (): MinioServerPool => ({
    id: nextPoolId,
    nodeCount,
    drivesPerNode,
    diskSizeTb,
    diskType,
    ecParity: syncedParity,
    ecParityUpgradePolicy,
    volumePath: templatePool.volumePath || "/data",
    ...(erasureStripeDrives != null ? { erasureStripeDrives } : {}),
  });

  const handleSubmit = async () => {
    setBusy(true);
    try {
      await onConfirm(buildPool());
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            New pool will be <span className="font-mono text-foreground">{nextPoolId}</span>.
            {isRunning
              ? " Adjust topology below, then apply. Docker will recreate MinIO peers with an updated expansion command (see note below)."
              : " Adjust capacity and resilience settings before adding the pool to the diagram."}
          </DialogDescription>
        </DialogHeader>

        {isRunning && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/90 leading-relaxed">
            <p className="font-medium text-amber-50 mb-1">Why S3 access can pause briefly</p>
            <p>
              In distributed MinIO, every peer must run the same <code className="text-[10px] bg-black/30 px-1 rounded">server</code> command listing{" "}
              <strong>all</strong> pools. Adding a pool changes that command for existing containers too, so Compose updates those services—not only the new pool.
              Expect a short window where the API may be unavailable while containers restart. True online expansion without peer restarts is not supported in this Docker Compose path.
            </p>
          </div>
        )}

        <div className="space-y-3 py-1">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Node count</label>
            <Select
              value={String(nodeCount)}
              onValueChange={(v) => {
                const n = parseInt(v, 10);
                const minDrives = n === 2 ? 2 : 1;
                const d = Math.max(drivesPerNode, minDrives);
                const newTotal = n * d;
                const keepStripe =
                  erasureStripeDrives != null &&
                  erasureStripeDrives > 0 &&
                  newTotal % erasureStripeDrives === 0;
                const stripeForParity = effectiveStripeSize(
                  newTotal,
                  keepStripe ? erasureStripeDrives : null,
                );
                const nextParity = clampParityToValidStripe(
                  stripeForParity,
                  ecParity ?? minioDefaultStandardParity(stripeForParity),
                );
                setNodeCount(n);
                if (d !== drivesPerNode) setDrivesPerNode(d);
                if (!keepStripe) setErasureStripeDrives(null);
                setEcParity(nextParity);
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

          <div>
            <label className="text-xs text-muted-foreground block mb-1">Drives per node</label>
            <Select
              value={String(drivesPerNode)}
              onValueChange={(v) => {
                const d = parseInt(v, 10);
                const newTotal = nodeCount * d;
                const keepStripe =
                  erasureStripeDrives != null &&
                  erasureStripeDrives > 0 &&
                  newTotal % erasureStripeDrives === 0;
                const stripeForParity = effectiveStripeSize(
                  newTotal,
                  keepStripe ? erasureStripeDrives : null,
                );
                const nextParity = clampParityToValidStripe(
                  stripeForParity,
                  ecParity ?? minioDefaultStandardParity(stripeForParity),
                );
                setDrivesPerNode(d);
                if (!keepStripe) setErasureStripeDrives(null);
                setEcParity(nextParity);
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
              {totalDrives} total drives → {numSets} × {setSize}-drive erasure set{numSets > 1 ? "s" : ""}
            </p>
          </div>

          {stripeChoices.length > 1 && (
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Erasure stripe width</label>
              <Select
                value={erasureStripeDrives == null ? "auto" : String(erasureStripeDrives)}
                onValueChange={(v) => {
                  if (v === "auto") {
                    const autoS = computeErasureSetSize(totalDrives);
                    setErasureStripeDrives(null);
                    setEcParity(
                      clampParityToValidStripe(
                        autoS,
                        ecParity ?? minioDefaultStandardParity(autoS),
                      ),
                    );
                    return;
                  }
                  const w = parseInt(v, 10);
                  setErasureStripeDrives(w);
                  setEcParity(
                    clampParityToValidStripe(w, ecParity ?? minioDefaultStandardParity(w)),
                  );
                }}
              >
                <SelectTrigger className="w-full h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">
                    Auto ({computeErasureSetSize(totalDrives)} drives/set)
                  </SelectItem>
                  {stripeChoices.map((w) => (
                    <SelectItem key={w} value={String(w)}>
                      {w} drives/set → {totalDrives / w} set{totalDrives / w > 1 ? "s" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div>
            <label className="text-xs text-muted-foreground block mb-1">Disk type</label>
            <Select value={diskType} onValueChange={(v) => setDiskType(v as DiskType)}>
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="nvme">NVMe SSD</SelectItem>
                <SelectItem value="ssd">SSD</SelectItem>
                <SelectItem value="hdd">HDD</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="text-xs text-muted-foreground block mb-1">Disk size per node (TB)</label>
            <Select value={String(diskSizeTb)} onValueChange={(v) => setDiskSizeTb(parseInt(v, 10))}>
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
            <p className="text-[10px] text-muted-foreground mt-0.5">Planning display; does not change container images.</p>
          </div>

          <div>
            <label className="text-xs text-muted-foreground block mb-1">EC setting (STANDARD)</label>
            {ecOptions.length === 0 ? (
              <p className="text-xs text-destructive leading-snug">
                No valid STANDARD EC for this drive count. Each stripe needs ≥4 drives with parity 2…½stripe.
              </p>
            ) : (
              <Select value={String(syncedParity)} onValueChange={(v) => setEcParity(parseInt(v, 10))}>
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
              <span className="font-mono">EC stripe:parity</span> per erasure set; deploy uses{" "}
              <span className="font-mono">MINIO_STORAGE_CLASS_STANDARD=EC:{syncedParity}</span>.
            </p>
          </div>

          <div>
            <label className="text-xs text-muted-foreground block mb-1">Parity upgrade policy</label>
            <Select value={ecParityUpgradePolicy} onValueChange={setEcParityUpgradePolicy}>
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="upgrade">upgrade</SelectItem>
                <SelectItem value="ignore">ignore</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="rounded-md border border-border/80 bg-muted/30 px-2 py-2 text-[10px] text-muted-foreground space-y-1">
            <div className="flex justify-between gap-2">
              <span>Usable capacity (planning)</span>
              <span className="font-mono text-foreground">{stats.usableTb} TB</span>
            </div>
            <div className="flex justify-between gap-2">
              <span>Erasure</span>
              <span className="font-mono text-foreground">
                {stats.numSets} × {stats.setSize} drives
              </span>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleSubmit()} disabled={busy}>
            {busy ? "Working…" : isRunning ? "Save & apply to Docker" : "Add pool"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
