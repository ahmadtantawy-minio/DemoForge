import type { MinioServerPool } from "../../../../types";
import type { computeClusterAggregates } from "../../../../lib/clusterUtils";

interface Props {
  loadBalancer?: boolean;
  mcpEnabled?: boolean;
  aistorTablesEnabled?: boolean;
  pools: MinioServerPool[];
  aggregates: ReturnType<typeof computeClusterAggregates>;
}

const badgeStyle: React.CSSProperties = {
  padding: "2px 7px",
  borderRadius: 5,
  fontSize: 10,
  borderWidth: 1,
  borderStyle: "solid",
  lineHeight: 1.3,
  display: "inline-flex",
  alignItems: "center",
  whiteSpace: "nowrap",
};

function diskTypeSummary(pools: MinioServerPool[]): string {
  const types = Array.from(new Set(pools.map((p) => p.diskType)));
  if (types.length === 0) return "SSD";
  if (types.length === 1) {
    const t = types[0];
    return t === "nvme" ? "NVMe" : t === "hdd" ? "HDD" : "SSD";
  }
  // Mixed
  const labels = types.map((t) => (t === "nvme" ? "NVMe" : t === "hdd" ? "HDD" : "SSD"));
  return labels.join("+");
}

export default function FeatureBadges({ mcpEnabled, aistorTablesEnabled, pools, aggregates }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-1 mb-2">
      <span
        style={badgeStyle}
        className="bg-blue-50/10 text-blue-400 border-blue-500/30"
        title="NGINX Load Balancer"
      >
        LB
      </span>
      {mcpEnabled && (
        <span
          style={badgeStyle}
          className="bg-violet-500/15 text-violet-400 border-violet-500/30"
          title="MCP AI Tools enabled"
        >
          MCP
        </span>
      )}
      {aistorTablesEnabled && (
        <span
          style={badgeStyle}
          className="bg-blue-700/15 text-blue-400 border-blue-700/30"
          title="AIStor Tables enabled"
        >
          Tables
        </span>
      )}
      <span
        style={badgeStyle}
        className="bg-zinc-500/10 text-zinc-300 border-zinc-500/30"
        title="Erasure coding"
      >
        {aggregates.ecSummary}
      </span>
      <span
        style={badgeStyle}
        className="bg-zinc-500/10 text-zinc-300 border-zinc-500/30"
        title="Disk type"
      >
        {diskTypeSummary(pools)}
      </span>
    </div>
  );
}
