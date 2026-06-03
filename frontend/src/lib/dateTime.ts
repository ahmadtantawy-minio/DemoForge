/** Format ISO UTC timestamps for UI (local timezone). */
export function formatLocalDateTime(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Relative time from ISO string (e.g. "3h ago"). */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff) || diff < 0) return "";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

export function formatUpdatedLabel(iso: string | null | undefined): string {
  if (!iso) return "Never saved";
  const rel = timeAgo(iso);
  const local = formatLocalDateTime(iso);
  return rel ? `Updated ${rel} · ${local}` : `Updated ${local}`;
}

/** Label for demo list rows: prefers last opened when newer than last save. */
export function formatDemoActivityLabel(
  updatedAt?: string | null,
  lastAccessedAt?: string | null,
): string {
  const updatedMs = updatedAt ? new Date(updatedAt).getTime() : 0;
  const accessedMs = lastAccessedAt ? new Date(lastAccessedAt).getTime() : 0;
  const useAccess = accessedMs > 0 && accessedMs >= updatedMs;
  const iso = useAccess ? lastAccessedAt : updatedAt;
  if (!iso) return "Never opened";
  const rel = timeAgo(iso);
  const local = formatLocalDateTime(iso);
  const verb = useAccess ? "Opened" : "Updated";
  return rel ? `${verb} ${rel} · ${local}` : `${verb} ${local}`;
}

export function demoActivityMs(d: {
  updated_at?: string | null;
  last_accessed_at?: string | null;
}): number {
  const updated = d.updated_at ? new Date(d.updated_at).getTime() : 0;
  const accessed = d.last_accessed_at ? new Date(d.last_accessed_at).getTime() : 0;
  return Math.max(updated, accessed);
}

export function sortDemosByActivity<T extends {
  updated_at?: string | null;
  last_accessed_at?: string | null;
}>(demos: T[]): T[] {
  return [...demos].sort((a, b) => demoActivityMs(b) - demoActivityMs(a));
}
