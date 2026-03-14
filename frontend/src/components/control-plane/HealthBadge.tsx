import type { HealthStatus } from "../../types";
import { Badge } from "@/components/ui/badge";

interface Props {
  health: HealthStatus;
}

const config: Record<HealthStatus, { dotColor: string; label: string }> = {
  healthy: { dotColor: "bg-green-500", label: "Healthy" },
  starting: { dotColor: "bg-yellow-400", label: "Starting" },
  degraded: { dotColor: "bg-orange-400", label: "Degraded" },
  error: { dotColor: "bg-red-500", label: "Error" },
  stopped: { dotColor: "bg-muted-foreground", label: "Stopped" },
};

export default function HealthBadge({ health }: Props) {
  const { dotColor, label } = config[health] ?? config.stopped;
  return (
    <Badge variant="outline" className="gap-1.5 text-xs font-medium">
      <span className={`inline-block w-2 h-2 rounded-full transition-colors duration-300 ${dotColor}`} />
      {label}
    </Badge>
  );
}
