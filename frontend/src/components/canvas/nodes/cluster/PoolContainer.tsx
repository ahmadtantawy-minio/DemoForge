import type { MinioServerPool } from "../../../../types";
import {
  computePoolErasureStats,
  effectiveStripeSize,
  clampParityToValidStripe,
  minioDefaultStandardParity,
} from "../../../../lib/erasure";

interface Props {
  pool: MinioServerPool;
  poolIndex: number;
  hidden: boolean;
  selected?: boolean;
  decommissionStatus?: "active" | "decommissioning" | "decommissioned";
  /** Latest line from ``mc admin decommission status`` (when draining). */
  decommissionDetail?: string;
  onPoolContextMenu: (e: React.MouseEvent) => void;
  onPoolClick?: (e: React.MouseEvent) => void;
  children: React.ReactNode;
}

function diskTypeLabel(t: MinioServerPool["diskType"]): string {
  return t === "nvme" ? "NVMe" : t === "hdd" ? "HDD" : "SSD";
}

export default function PoolContainer({
  pool,
  poolIndex,
  hidden,
  selected,
  decommissionStatus,
  decommissionDetail,
  children,
  onPoolContextMenu,
  onPoolClick,
}: Props) {
  const td = pool.nodeCount * pool.drivesPerNode;
  const stripe = effectiveStripeSize(td, pool.erasureStripeDrives ?? null);
  const par = clampParityToValidStripe(stripe, pool.ecParity ?? minioDefaultStandardParity(stripe));
  const stats = computePoolErasureStats(
    pool.nodeCount,
    pool.drivesPerNode,
    par,
    pool.diskSizeTb,
    pool.erasureStripeDrives,
  );

  if (hidden) {
    return (
      <div onContextMenu={onPoolContextMenu}>
        <div
          onClick={onPoolClick}
          style={{ cursor: "pointer", marginBottom: 6, display: "inline-block", opacity: 0.6 }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = "1"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = "0.6"; }}
        >
          <span className="text-[10px] text-muted-foreground">
            Pool {poolIndex} — {pool.nodeCount} × {pool.drivesPerNode} {diskTypeLabel(pool.diskType)} drives
          </span>
        </div>
        <div className="flex gap-2.5 flex-wrap">{children}</div>
      </div>
    );
  }

  return (
    <div
      onContextMenu={onPoolContextMenu}
      style={{
        border: selected ? "1px solid #3b82f6" : "1px dashed rgba(161,161,170,0.5)",
        borderRadius: 10,
        padding: 10,
        marginBottom: 8,
      }}
    >
      <div
        className="flex items-center justify-between mb-2"
        onClick={onPoolClick}
        style={{ cursor: onPoolClick ? "pointer" : undefined }}
      >
        <div className="flex items-center gap-1.5">
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "#1D9E75",
              display: "inline-block",
            }}
          />
          <span className="text-[11px] font-semibold text-foreground">Pool {poolIndex}</span>
          <span className="text-[11px] text-muted-foreground">
            — {pool.nodeCount} × {pool.drivesPerNode} {diskTypeLabel(pool.diskType)} drives
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {decommissionStatus === "decommissioning" && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-orange-500/20 text-orange-400 font-medium">
              Decommissioning
            </span>
          )}
          {decommissionStatus === "decommissioned" && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400 font-medium">
              Decommissioned
            </span>
          )}
          <span className="text-[10px] text-muted-foreground">{stats.usableTb} TB</span>
        </div>
      </div>
      {decommissionStatus === "decommissioning" && decommissionDetail && (
        <p className="text-[9px] text-muted-foreground leading-snug mb-2 font-mono break-words opacity-90">
          {decommissionDetail.length > 120 ? `${decommissionDetail.slice(0, 120)}…` : decommissionDetail}
        </p>
      )}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}
