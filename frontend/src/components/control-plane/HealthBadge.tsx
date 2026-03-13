import type { HealthStatus } from "../../types";

interface Props {
  health: HealthStatus;
}

const config: Record<HealthStatus, { color: string; label: string }> = {
  healthy: { color: "bg-green-500", label: "Healthy" },
  starting: { color: "bg-yellow-400", label: "Starting" },
  degraded: { color: "bg-orange-400", label: "Degraded" },
  error: { color: "bg-red-500", label: "Error" },
  stopped: { color: "bg-gray-400", label: "Stopped" },
};

export default function HealthBadge({ health }: Props) {
  const { color, label } = config[health] ?? config.stopped;
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium">
      <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}
