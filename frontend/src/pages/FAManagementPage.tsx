import { useCallback, useEffect, useState } from "react";
import {
  fetchAdminStats,
  fetchFAs,
  fetchFA,
  fetchFAActivity,
  updateFAPermissions,
  updateFAStatus,
  purgeFA,
  type AdminStats,
  type FAListItem,
  type FAProfile,
  type FAActivity,
  type FAPermissions,
} from "../api/faAdmin";
import { toast } from "../lib/toast";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import {
  Users,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Activity,
  BarChart3,
  Shield,
  XCircle,
  Trash2,
} from "lucide-react";
import { cn } from "../lib/utils";

const EVENT_TYPES = [
  "all",
  "demo_deployed",
  "demo_stopped",
  "template_forked",
  "template_published",
  "app_started",
  "app_stopped",
];

function formatDate(iso: string | null) {
  if (!iso) return "--";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "--";
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(diff / 3600000);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(diff / 86400000);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-card border rounded-lg px-4 py-3 flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-bold text-foreground">{value}</span>
      {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
    </div>
  );
}

function PermissionToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <span className="text-sm text-foreground">{label}</span>
      <button
        onClick={() => onChange(!value)}
        className={cn(
          "inline-flex items-center justify-center w-10 h-6 rounded-full transition-colors border",
          value ? "bg-green-600 border-green-500" : "bg-zinc-800 border-zinc-700"
        )}
      >
        <span
          className={cn(
            "block w-4 h-4 rounded-full bg-white transition-transform",
            value ? "translate-x-2" : "-translate-x-2"
          )}
        />
      </button>
    </div>
  );
}

function FADetailPanel({
  fa,
  onClose,
  onUpdated,
  onPurged,
}: {
  fa: FAProfile;
  onClose: () => void;
  onUpdated: (updated: FAProfile) => void;
  onPurged: (faId: string) => void;
}) {
  const [perms, setPerms] = useState<FAPermissions>({ ...fa.permissions });
  const [saving, setSaving] = useState(false);
  const [confirmingPurge, setConfirmingPurge] = useState(false);
  const [purging, setPurging] = useState(false);
  const [activities, setActivities] = useState<FAActivity[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [eventTypeFilter, setEventTypeFilter] = useState("all");
  const [activityOffset, setActivityOffset] = useState(0);

  const PAGE_SIZE = 20;

  const loadActivity = useCallback(
    async (offset = 0, filter = eventTypeFilter) => {
      setActivityLoading(true);
      try {
        const data = await fetchFAActivity(fa.fa_id, {
          event_type: filter === "all" ? undefined : filter,
          limit: PAGE_SIZE,
          offset,
        });
        setActivities(data);
        setActivityOffset(offset);
      } catch {
        toast.error("Failed to load activity");
      } finally {
        setActivityLoading(false);
      }
    },
    [fa.fa_id, eventTypeFilter]
  );

  useEffect(() => {
    loadActivity(0, "all");
  }, [fa.fa_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFilterChange = (f: string) => {
    setEventTypeFilter(f);
    loadActivity(0, f);
  };

  const handleSavePerms = async () => {
    setSaving(true);
    try {
      const updated = await updateFAPermissions(fa.fa_id, perms);
      onUpdated(updated);
      toast.success("Permissions updated");
    } catch {
      toast.error("Failed to update permissions");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleStatus = async () => {
    try {
      const updated = await updateFAStatus(fa.fa_id, !fa.is_active);
      onUpdated(updated);
      toast.success(`${fa.fa_id} ${updated.is_active ? "activated" : "deactivated"}`);
    } catch {
      toast.error("Failed to update status");
    }
  };

  const handlePurge = async () => {
    setPurging(true);
    try {
      await purgeFA(fa.fa_id);
      toast.success(`${fa.fa_id} purged — can be re-registered`);
      onPurged(fa.fa_id);
    } catch {
      toast.error("Failed to purge FA");
      setPurging(false);
      setConfirmingPurge(false);
    }
  };

  return (
    <div className="border-t border-border bg-card/50">
      <div className="max-w-5xl mx-auto px-8 py-4">
        {/* Detail header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-zinc-700 flex items-center justify-center text-xs font-bold text-zinc-200">
              {fa.fa_name?.charAt(0)?.toUpperCase() || fa.fa_id.charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">{fa.fa_name || fa.fa_id}</p>
              <p className="text-xs text-muted-foreground">{fa.fa_id}</p>
            </div>
            <Badge
              variant="outline"
              className={cn(
                "text-[10px] px-1.5 py-0",
                fa.is_active
                  ? "border-green-500/40 text-green-400 bg-green-500/10"
                  : "border-red-500/40 text-red-400 bg-red-500/10"
              )}
            >
              {fa.is_active ? "Active" : "Inactive"}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleToggleStatus}
              className={cn(
                "px-3 py-1.5 text-xs rounded-md border transition-colors",
                fa.is_active
                  ? "border-red-700 text-red-400 hover:bg-red-900/30"
                  : "border-green-700 text-green-400 hover:bg-green-900/30"
              )}
            >
              {fa.is_active ? "Deactivate" : "Activate"}
            </button>
            {confirmingPurge ? (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-red-400">Purge all data?</span>
                <button
                  onClick={handlePurge}
                  disabled={purging}
                  className="px-2 py-1 text-xs rounded-md border border-red-700 bg-red-900/40 text-red-300 hover:bg-red-900/70 transition-colors disabled:opacity-50"
                >
                  {purging ? "Purging…" : "Confirm"}
                </button>
                <button
                  onClick={() => setConfirmingPurge(false)}
                  className="px-2 py-1 text-xs rounded-md border border-zinc-700 text-zinc-400 hover:bg-zinc-800 transition-colors"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmingPurge(true)}
                className="p-1.5 rounded-md border border-zinc-700 text-zinc-500 hover:border-red-700 hover:text-red-400 hover:bg-red-900/20 transition-colors"
                title="Purge FA (hard delete — can be re-registered)"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-zinc-800 text-muted-foreground transition-colors"
            >
              <XCircle className="w-4 h-4" />
            </button>
          </div>
        </div>

        <Tabs defaultValue="permissions">
          <TabsList>
            <TabsTrigger value="permissions">
              <Shield className="w-3.5 h-3.5 mr-1.5" />
              Permissions
            </TabsTrigger>
            <TabsTrigger value="activity">
              <Activity className="w-3.5 h-3.5 mr-1.5" />
              Activity
            </TabsTrigger>
          </TabsList>

          {/* Permissions tab */}
          <TabsContent value="permissions">
            <div className="bg-card border rounded-lg p-4 max-w-sm">
              <PermissionToggle
                label="Manual Demo Creation"
                value={perms.manual_demo_creation}
                onChange={(v) => setPerms((p) => ({ ...p, manual_demo_creation: v }))}
              />
              <PermissionToggle
                label="Fork Templates"
                value={perms.template_fork}
                onChange={(v) => setPerms((p) => ({ ...p, template_fork: v }))}
              />
              <PermissionToggle
                label="Publish Templates"
                value={perms.template_publish}
                onChange={(v) => setPerms((p) => ({ ...p, template_publish: v }))}
              />
              <div className="flex items-center justify-between py-2">
                <label className="text-sm text-foreground">Max Concurrent Demos</label>
                <Input
                  type="number"
                  min={1}
                  max={20}
                  value={perms.max_concurrent_demos}
                  onChange={(e) =>
                    setPerms((p) => ({ ...p, max_concurrent_demos: parseInt(e.target.value) || 1 }))
                  }
                  className="w-16 h-7 text-xs text-center"
                />
              </div>
              <button
                onClick={handleSavePerms}
                disabled={saving}
                className="mt-3 w-full py-1.5 text-xs rounded-md bg-zinc-700 hover:bg-zinc-600 text-zinc-100 border border-zinc-600 transition-colors disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Permissions"}
              </button>
            </div>
          </TabsContent>

          {/* Activity tab */}
          <TabsContent value="activity">
            {/* Filter */}
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs text-muted-foreground">Event type:</span>
              <div className="flex gap-1 flex-wrap">
                {EVENT_TYPES.map((t) => (
                  <button
                    key={t}
                    onClick={() => handleFilterChange(t)}
                    className={cn(
                      "px-2 py-1 text-[10px] rounded border transition-colors",
                      eventTypeFilter === t
                        ? "bg-zinc-800 border-zinc-600 text-zinc-100"
                        : "border-transparent text-muted-foreground hover:bg-muted"
                    )}
                  >
                    {t === "all" ? "All" : t.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>

            {activityLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-10 bg-muted rounded animate-pulse" />
                ))}
              </div>
            ) : activities.length === 0 ? (
              <div className="bg-card border rounded-lg p-6 text-center">
                <p className="text-sm text-muted-foreground">No events found.</p>
              </div>
            ) : (
              <>
                <div className="bg-card border rounded-lg overflow-hidden">
                  <div className="grid grid-cols-[140px_1fr_150px] gap-2 px-4 py-2 bg-muted border-b text-xs font-medium text-muted-foreground">
                    <span>Event</span>
                    <span>Payload</span>
                    <span className="text-right">Time</span>
                  </div>
                  <div className="divide-y divide-border max-h-64 overflow-y-auto">
                    {activities.map((ev) => (
                      <div
                        key={ev.id}
                        className="grid grid-cols-[140px_1fr_150px] gap-2 px-4 py-2 items-center"
                      >
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0 w-fit">
                          {ev.event_type.replace(/_/g, " ")}
                        </Badge>
                        <span className="text-xs text-muted-foreground truncate font-mono">
                          {Object.keys(ev.payload).length > 0
                            ? JSON.stringify(ev.payload).slice(0, 80)
                            : "{}"}
                        </span>
                        <span className="text-xs text-muted-foreground text-right">
                          {formatDate(ev.timestamp)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                {/* Pagination */}
                <div className="flex justify-end gap-2 mt-2">
                  {activityOffset > 0 && (
                    <button
                      onClick={() => loadActivity(activityOffset - PAGE_SIZE)}
                      className="px-3 py-1 text-xs rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors"
                    >
                      ← Prev
                    </button>
                  )}
                  {activities.length === PAGE_SIZE && (
                    <button
                      onClick={() => loadActivity(activityOffset + PAGE_SIZE)}
                      className="px-3 py-1 text-xs rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors"
                    >
                      Next →
                    </button>
                  )}
                </div>
              </>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

export function FAManagementPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [fas, setFas] = useState<FAListItem[]>([]);
  const [selectedFAId, setSelectedFAId] = useState<string | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<FAProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsData, fasData] = await Promise.all([fetchAdminStats(), fetchFAs()]);
      setStats(statsData);
      setFas(fasData);
    } catch (e: any) {
      setError(e.message || "Failed to load FA management data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSelectFA = async (faId: string) => {
    if (selectedFAId === faId) {
      setSelectedFAId(null);
      setSelectedProfile(null);
      return;
    }
    setSelectedFAId(faId);
    setProfileLoading(true);
    try {
      const profile = await fetchFA(faId);
      setSelectedProfile(profile);
    } catch {
      toast.error("Failed to load FA profile");
      setSelectedFAId(null);
    } finally {
      setProfileLoading(false);
    }
  };

  const handleProfileUpdated = (updated: FAProfile) => {
    setSelectedProfile(updated);
    setFas((prev) =>
      prev.map((f) =>
        f.fa_id === updated.fa_id ? { ...f, is_active: updated.is_active } : f
      )
    );
  };

  const handleProfilePurged = (faId: string) => {
    setFas((prev) => prev.filter((f) => f.fa_id !== faId));
    setSelectedFAId(null);
    setSelectedProfile(null);
    if (stats) setStats({ ...stats, total_fas: stats.total_fas - 1, active_fas: Math.max(0, stats.active_fas - 1) });
  };

  // Skeleton loading
  if (loading) {
    return (
      <div className="h-full overflow-auto bg-background">
        <div className="max-w-5xl mx-auto px-8 py-8">
          <div className="h-8 w-56 bg-muted rounded animate-pulse mb-6" />
          <div className="grid grid-cols-4 gap-4 mb-6">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-20 bg-muted rounded animate-pulse" />
            ))}
          </div>
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 bg-muted rounded animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    const isNotConfigured = error.includes("not configured") || error.includes("dev-init");
    return (
      <div className="h-full overflow-auto bg-background">
        <div className="max-w-5xl mx-auto px-8 py-8">
          <div className="flex items-center gap-3 mb-6">
            <Users className="w-6 h-6 text-muted-foreground" />
            <h1 className="text-2xl font-bold text-card-foreground">FA Management</h1>
          </div>
          <div className={`bg-card border rounded-lg p-8 text-center ${isNotConfigured ? "border-zinc-700" : "border-red-800/50"}`}>
            {isNotConfigured
              ? <Users className="w-10 h-10 text-zinc-500 mx-auto mb-3" />
              : <XCircle className="w-10 h-10 text-red-400 mx-auto mb-3" />}
            <p className="text-sm font-medium text-foreground mb-2">
              {isNotConfigured ? "Hub API not configured" : "Failed to load FA data"}
            </p>
            <p className="text-xs text-muted-foreground mb-5 max-w-md mx-auto">
              {isNotConfigured
                ? <>Run <code className="bg-muted px-1 rounded">make dev-init</code> to generate a local admin key, then restart the backend.</>
                : error}
            </p>
            {!isNotConfigured && (
              <button
                onClick={load}
                className="px-4 py-2 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors"
              >
                Retry
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-background">
      <div className="max-w-5xl mx-auto px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Users className="w-6 h-6 text-muted-foreground" />
            <h1 className="text-2xl font-bold text-card-foreground">FA Management</h1>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        </div>

        {/* Stats cards */}
        {stats && (
          <div className="grid grid-cols-4 gap-4 mb-6">
            <StatCard label="Total FAs" value={stats.total_fas} />
            <StatCard label="Active FAs" value={stats.active_fas} />
            <StatCard
              label="Events (7d)"
              value={stats.events_last_7_days}
              sub={`${stats.total_events} total`}
            />
            <StatCard label="Events (30d)" value={stats.events_last_30_days} />
          </div>
        )}

        {/* Events by type mini-chart */}
        {stats && Object.keys(stats.events_by_type).length > 0 && (
          <div className="bg-card border rounded-lg p-4 mb-6">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm font-medium text-card-foreground">Events by Type</span>
            </div>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.events_by_type)
                .sort(([, a], [, b]) => b - a)
                .map(([type, count]) => (
                  <div key={type} className="flex items-center gap-1.5">
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      {type.replace(/_/g, " ")}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{count}</span>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* FA table */}
        {fas.length === 0 ? (
          <div className="bg-card border rounded-lg p-8 text-center">
            <p className="text-sm text-muted-foreground">No Field Architects registered yet.</p>
          </div>
        ) : (
          <div className="bg-card border rounded-lg overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_120px_80px_120px_120px_80px_32px] gap-2 px-4 py-2 bg-muted border-b text-xs font-medium text-muted-foreground">
              <span>FA ID</span>
              <span>Name</span>
              <span className="text-center">Status</span>
              <span>Registered</span>
              <span>Last Seen</span>
              <span className="text-center">Events</span>
              <span />
            </div>
            <div className="divide-y divide-border">
              {fas.map((fa) => {
                const isExpanded = selectedFAId === fa.fa_id;
                return (
                  <div key={fa.fa_id}>
                    <div
                      className="grid grid-cols-[1fr_120px_80px_120px_120px_80px_32px] gap-2 px-4 py-2.5 items-center hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => handleSelectFA(fa.fa_id)}
                    >
                      <span className="text-sm font-medium text-foreground truncate font-mono">
                        {fa.fa_id}
                      </span>
                      <span className="text-sm text-muted-foreground truncate">{fa.fa_name || "--"}</span>
                      <span className="text-center">
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[10px] px-1.5 py-0",
                            fa.is_active
                              ? "border-green-500/40 text-green-400 bg-green-500/10"
                              : "border-red-500/40 text-red-400 bg-red-500/10"
                          )}
                        >
                          {fa.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </span>
                      <span className="text-xs text-muted-foreground">{formatDate(fa.registered_at)}</span>
                      <span className="text-xs text-muted-foreground">{formatDate(fa.last_seen_at)}</span>
                      <span className="text-center">
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {fa.event_count}
                        </Badge>
                      </span>
                      <span className="flex justify-center text-muted-foreground">
                        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </span>
                    </div>

                    {/* Expanded detail */}
                    {isExpanded && (
                      profileLoading ? (
                        <div className="px-8 py-4 border-t border-border">
                          <div className="space-y-2">
                            {[1, 2].map((i) => (
                              <div key={i} className="h-8 bg-muted rounded animate-pulse" />
                            ))}
                          </div>
                        </div>
                      ) : selectedProfile ? (
                        <FADetailPanel
                          fa={selectedProfile}
                          onClose={() => { setSelectedFAId(null); setSelectedProfile(null); }}
                          onUpdated={handleProfileUpdated}
                          onPurged={handleProfilePurged}
                        />
                      ) : null
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
