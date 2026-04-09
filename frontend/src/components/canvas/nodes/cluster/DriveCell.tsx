import { useState } from "react";

interface Props {
  status: "healthy" | "failed" | "healing" | "offline";
  onContextMenu: (e: React.MouseEvent) => void;
}

const COLORS: Record<Props["status"], string> = {
  healthy: "#1D9E75",
  failed: "#E24B4A",
  healing: "#EF9F27",
  offline: "rgba(113,113,122,0.3)",
};

export default function DriveCell({ status, onContextMenu }: Props) {
  const [hover, setHover] = useState(false);
  const color = COLORS[status];
  return (
    <div
      onContextMenu={onContextMenu}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: 8,
        height: 6,
        borderRadius: 1,
        background: color,
        cursor: "pointer",
        transition: "all 0.12s ease",
        transform: hover ? "scale(1.4)" : "scale(1)",
        boxShadow: hover ? `0 0 0 1px ${color}` : undefined,
        zIndex: hover ? 2 : undefined,
        position: "relative",
      }}
    />
  );
}
