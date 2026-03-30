import { Loader2 } from "lucide-react";

interface Props {
  status: "cached" | "missing" | "pulling" | "unknown";
  progressPct?: number | null;
}

export function ImageStatusBadge({ status, progressPct }: Props) {
  return (
    <span data-testid="image-status-badge" className="inline-flex items-center gap-1.5 text-xs font-medium">
      {status === "cached" && (
        <>
          <span className="w-2 h-2 rounded-full bg-green-500" />
          <span className="text-green-400">Cached</span>
        </>
      )}
      {status === "missing" && (
        <>
          <span className="w-2 h-2 rounded-full bg-red-500" />
          <span className="text-red-400">Missing</span>
        </>
      )}
      {status === "pulling" && (
        <>
          <Loader2 data-testid="pull-spinner" className="w-3 h-3 animate-spin text-blue-400" />
          <span className="text-blue-400">Pulling{progressPct != null ? ` ${progressPct}%` : ""}</span>
        </>
      )}
      {status === "unknown" && (
        <>
          <span className="w-2 h-2 rounded-full bg-zinc-500" />
          <span className="text-zinc-400">Unknown</span>
        </>
      )}
    </span>
  );
}
