import type { computeClusterAggregates } from "../../../../lib/clusterUtils";

interface Props {
  aggregates: ReturnType<typeof computeClusterAggregates>;
}

export default function CapacityBar({ aggregates }: Props) {
  const { totalRawTb, totalUsableTb } = aggregates;
  const pct = totalRawTb > 0 ? Math.round((totalUsableTb / totalRawTb) * 100) : 0;
  return (
    <div className="mt-2">
      <div
        style={{
          width: "100%",
          height: 3,
          background: "rgba(212,212,216,0.2)",
          borderRadius: 1.5,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: "#1D9E75",
            borderRadius: 1.5,
          }}
        />
      </div>
      <div className="text-[9px] text-muted-foreground mt-0.5">
        {totalUsableTb} TB / {totalRawTb} TB raw  {pct}% usable
      </div>
    </div>
  );
}
