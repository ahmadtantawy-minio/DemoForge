import type { ContainerInstance } from "../../../../types";
import DriveCell from "./DriveCell";

interface Props {
  nodeIndex: number;
  drivesPerNode: number;
  isRunning: boolean;
  instance: ContainerInstance | undefined;
  selected?: boolean;
  onNodeSelect?: (e: React.MouseEvent) => void;
  onNodeContextMenu: (e: React.MouseEvent) => void;
  onDriveContextMenu: (driveIndex: number, e: React.MouseEvent) => void;
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

export default function NodeTile({
  nodeIndex,
  drivesPerNode,
  isRunning,
  instance,
  selected,
  onNodeSelect,
  onNodeContextMenu,
  onDriveContextMenu,
}: Props) {
  const isStopped = instance?.health === "stopped";
  const dimmed = !isRunning || isStopped;

  return (
    <div
      data-node-icon
      onClick={(e) => {
        e.stopPropagation();
        if (onNodeSelect) onNodeSelect(e);
      }}
      onContextMenu={onNodeContextMenu}
      style={{
        opacity: dimmed ? 0.4 : 1,
        cursor: "pointer",
        display: "inline-block",
      }}
      title={instance ? `${instance.node_id} (${instance.health})` : `Node ${nodeIndex}`}
    >
      <div
        style={{
          width: 42,
          height: 28,
          background: "#1d1d1d",
          borderRadius: "6px 6px 2px 2px",
          color: "#C72C48",
          fontSize: 12,
          fontWeight: "bold",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: selected ? "0 0 0 2px #3b82f6" : undefined,
        }}
      >
        M
      </div>
      <div
        style={{
          width: 42,
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 1.5,
          padding: 2,
          borderRadius: "2px 2px 6px 6px",
          border: "0.5px solid rgba(212,212,216,0.2)",
          background: "rgba(244,244,245,0.08)",
          justifyItems: "center",
          alignItems: "center",
        }}
      >
        {Array.from({ length: drivesPerNode }, (_, d) => (
          <DriveCell
            key={d}
            status={driveStatus(instance, d + 1, isRunning)}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onDriveContextMenu(d, e);
            }}
          />
        ))}
      </div>
      <div
        style={{
          fontSize: 8,
          color: "var(--muted-foreground, rgba(161,161,170,0.8))",
          textAlign: "center",
          marginTop: 2,
          whiteSpace: "nowrap",
        }}
      >
        node-{nodeIndex}
      </div>
    </div>
  );
}
