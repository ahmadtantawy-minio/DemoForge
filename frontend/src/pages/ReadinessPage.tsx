import { useEffect, useState, useCallback } from "react";
import {
  fetchComponentReadiness,
  fetchTemplateReadiness,
  updateComponentReadiness,
  type ComponentReadinessItem,
  type TemplateReadinessItem,
} from "../api/readiness";
import { toast } from "../lib/toast";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { RefreshCw, Search, CheckCircle2, XCircle, ShieldCheck } from "lucide-react";
import { cn } from "../lib/utils";
import { EdgeInventoryTab } from "../components/readiness/EdgeInventoryTab";

type FilterType = "all" | "ready" | "not_ready";

export function ReadinessPage() {
  const [components, setComponents] = useState<ComponentReadinessItem[]>([]);
  const [templates, setTemplates] = useState<TemplateReadinessItem[]>([]);
  const [compSummary, setCompSummary] = useState({ total: 0, fa_ready: 0, not_ready: 0 });
  const [tmplSummary, setTmplSummary] = useState({ total: 0, fa_ready: 0, not_ready: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [compFilter, setCompFilter] = useState<FilterType>("all");
  const [tmplFilter, setTmplFilter] = useState<FilterType>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [compRes, tmplRes] = await Promise.all([
        fetchComponentReadiness(),
        fetchTemplateReadiness(),
      ]);
      setComponents(compRes.components);
      setCompSummary(compRes.summary);
      setTemplates(tmplRes.templates);
      setTmplSummary(tmplRes.summary);
    } catch (err: any) {
      setError(err.message || "Failed to load readiness data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggleReady = async (comp: ComponentReadinessItem) => {
    const newVal = !comp.fa_ready;
    // Optimistic update
    setComponents((prev) =>
      prev.map((c) =>
        c.component_id === comp.component_id ? { ...c, fa_ready: newVal } : c
      )
    );
    setCompSummary((prev) => ({
      ...prev,
      fa_ready: prev.fa_ready + (newVal ? 1 : -1),
      not_ready: prev.not_ready + (newVal ? -1 : 1),
    }));
    try {
      await updateComponentReadiness(comp.component_id, newVal);
      toast.success(`${comp.component_name} marked as ${newVal ? "FA Ready" : "Not Ready"}`);
    } catch {
      // Revert
      setComponents((prev) =>
        prev.map((c) =>
          c.component_id === comp.component_id ? { ...c, fa_ready: !newVal } : c
        )
      );
      setCompSummary((prev) => ({
        ...prev,
        fa_ready: prev.fa_ready + (newVal ? -1 : 1),
        not_ready: prev.not_ready + (newVal ? 1 : -1),
      }));
      toast.error(`Failed to update ${comp.component_name}`);
    }
  };

  const filteredComponents = components.filter((c) => {
    if (compFilter === "ready" && !c.fa_ready) return false;
    if (compFilter === "not_ready" && c.fa_ready) return false;
    if (search && !c.component_name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const filteredTemplates = templates.filter((t) => {
    if (tmplFilter === "ready" && !t.is_fa_ready) return false;
    if (tmplFilter === "not_ready" && t.is_fa_ready) return false;
    return true;
  });

  const formatDate = (iso: string | null) => {
    if (!iso) return "--";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "--";
    const now = Date.now();
    const diff = now - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(diff / 3600000);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(diff / 86400000);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const truncate = (s: string, max = 50) =>
    s.length > max ? s.slice(0, max) + "..." : s;

  const progressPct = compSummary.total > 0 ? (compSummary.fa_ready / compSummary.total) * 100 : 0;

  // Skeleton loading
  if (loading) {
    return (
      <div data-testid="readiness-page" className="h-full overflow-auto bg-background">
        <div className="max-w-7xl mx-auto px-8 py-8">
          <div className="flex items-center justify-between mb-6">
            <div className="h-8 w-48 bg-muted rounded animate-pulse" />
            <div className="h-9 w-24 bg-muted rounded animate-pulse" />
          </div>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 bg-muted rounded animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div data-testid="readiness-page" className="h-full overflow-auto bg-background">
        <div className="max-w-7xl mx-auto px-8 py-8">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-bold text-card-foreground">Readiness</h1>
          </div>
          <div className="bg-card border border-red-800/50 rounded-lg p-8 text-center">
            <XCircle className="w-10 h-10 text-red-400 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground mb-4">{error}</p>
            <button
              onClick={load}
              className="px-4 py-2 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="readiness-page" className="h-full overflow-auto bg-background">
      <div className="max-w-7xl mx-auto px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-6 h-6 text-muted-foreground" />
            <h1 className="text-2xl font-bold text-card-foreground">Readiness</h1>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        </div>

        <Tabs defaultValue="components">
          <TabsList>
            <TabsTrigger value="components">Components</TabsTrigger>
            <TabsTrigger value="templates">Templates</TabsTrigger>
            <TabsTrigger value="edges">Edge inventory</TabsTrigger>
          </TabsList>

          {/* Components Tab */}
          <TabsContent value="components">
            {/* Summary bar */}
            <div className="bg-card border rounded-lg p-4 mb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-card-foreground">
                  {compSummary.fa_ready} of {compSummary.total} components FA Ready
                </span>
                <span className="text-xs text-muted-foreground">
                  {Math.round(progressPct)}%
                </span>
              </div>
              <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500 rounded-full transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>

            {/* Search + Filters */}
            <div className="flex items-center gap-3 mb-4">
              <div className="relative flex-1 max-w-xs">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search components..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9 h-9"
                />
              </div>
              <div className="flex gap-1">
                {(["all", "ready", "not_ready"] as FilterType[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setCompFilter(f)}
                    className={cn(
                      "px-3 py-1.5 text-xs rounded-md border transition-colors",
                      compFilter === f
                        ? "bg-zinc-800 border-zinc-700 text-zinc-100"
                        : "border-transparent text-muted-foreground hover:bg-muted"
                    )}
                  >
                    {f === "all" ? "All" : f === "ready" ? "FA Ready" : "Not Ready"}
                  </button>
                ))}
              </div>
            </div>

            {/* Empty state */}
            {filteredComponents.length === 0 ? (
              <div className="bg-card border rounded-lg p-8 text-center">
                <p className="text-sm text-muted-foreground">No components found.</p>
              </div>
            ) : (
              <div className="bg-card border rounded-lg overflow-hidden">
                {/* Table header */}
                <div className="grid grid-cols-[1fr_100px_80px_80px_140px_100px] gap-2 px-4 py-2 bg-muted border-b border-border text-xs font-medium text-muted-foreground">
                  <span>Name</span>
                  <span>Category</span>
                  <span className="text-center">FA Ready</span>
                  <span className="text-center">Templates</span>
                  <span>Notes</span>
                  <span className="text-right">Updated</span>
                </div>
                <div className="divide-y divide-border">
                  {filteredComponents.map((comp) => (
                    <div
                      key={comp.component_id}
                      className="grid grid-cols-[1fr_100px_80px_80px_140px_100px] gap-2 px-4 py-2.5 items-center hover:bg-muted/50 transition-colors"
                    >
                      <span className="text-sm font-medium text-foreground truncate">
                        {comp.component_name}
                      </span>
                      <span>
                        <Badge
                          variant="secondary"
                          className="text-[10px] px-1.5 py-0"
                        >
                          {comp.category}
                        </Badge>
                      </span>
                      <span className="text-center">
                        <button
                          onClick={() => handleToggleReady(comp)}
                          className={cn(
                            "inline-flex items-center justify-center w-10 h-6 rounded-full transition-colors border",
                            comp.fa_ready
                              ? "bg-green-600 border-green-500"
                              : "bg-zinc-800 border-zinc-700"
                          )}
                          title={comp.fa_ready ? "Mark Not Ready" : "Mark FA Ready"}
                        >
                          <span
                            className={cn(
                              "block w-4 h-4 rounded-full bg-white transition-transform",
                              comp.fa_ready ? "translate-x-2" : "-translate-x-2"
                            )}
                          />
                        </button>
                      </span>
                      <span className="text-center">
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {comp.template_count}
                        </Badge>
                      </span>
                      <span
                        className="text-xs text-muted-foreground truncate"
                        title={comp.notes || undefined}
                      >
                        {comp.notes ? truncate(comp.notes) : "--"}
                      </span>
                      <span className="text-xs text-muted-foreground text-right">
                        {formatDate(comp.updated_at)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>

          {/* Templates Tab */}
          <TabsContent value="templates">
            {/* Summary bar */}
            <div className="bg-card border rounded-lg p-4 mb-4">
              <span className="text-sm font-medium text-card-foreground">
                {tmplSummary.fa_ready} of {tmplSummary.total} templates FA Ready
              </span>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-3 mb-4">
              <div className="flex gap-1">
                {(["all", "ready", "not_ready"] as FilterType[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setTmplFilter(f)}
                    className={cn(
                      "px-3 py-1.5 text-xs rounded-md border transition-colors",
                      tmplFilter === f
                        ? "bg-zinc-800 border-zinc-700 text-zinc-100"
                        : "border-transparent text-muted-foreground hover:bg-muted"
                    )}
                  >
                    {f === "all" ? "All" : f === "ready" ? "FA Ready" : "Not Ready"}
                  </button>
                ))}
              </div>
            </div>

            {/* Empty state */}
            {filteredTemplates.length === 0 ? (
              <div className="bg-card border rounded-lg p-8 text-center">
                <p className="text-sm text-muted-foreground">No templates found.</p>
              </div>
            ) : (
              <div className="bg-card border rounded-lg overflow-hidden">
                {/* Table header */}
                <div className="grid grid-cols-[1fr_90px_80px_100px_1fr] gap-2 px-4 py-2 bg-muted border-b border-border text-xs font-medium text-muted-foreground">
                  <span>Template Name</span>
                  <span>Source</span>
                  <span className="text-center">FA Ready</span>
                  <span className="text-center">Components</span>
                  <span>Blocking</span>
                </div>
                <div className="divide-y divide-border">
                  {filteredTemplates.map((tmpl) => (
                    <div
                      key={tmpl.template_id}
                      className="grid grid-cols-[1fr_90px_80px_100px_1fr] gap-2 px-4 py-2.5 items-center hover:bg-muted/50 transition-colors"
                    >
                      <span className="text-sm font-medium text-foreground truncate">
                        {tmpl.template_name}
                      </span>
                      <span>
                        <Badge
                          variant="secondary"
                          className={cn(
                            "text-[10px] px-1.5 py-0",
                            tmpl.source === "builtin"
                              ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                              : tmpl.source === "synced"
                              ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                              : "bg-zinc-500/10 text-zinc-400 border-zinc-500/20"
                          )}
                        >
                          {tmpl.source}
                        </Badge>
                      </span>
                      <span className="text-center">
                        {tmpl.is_fa_ready ? (
                          <CheckCircle2 className="w-4 h-4 text-green-400 inline-block" />
                        ) : (
                          <XCircle className="w-4 h-4 text-red-400 inline-block" />
                        )}
                      </span>
                      <span className="text-center text-xs text-muted-foreground">
                        {tmpl.ready_component_count}/{tmpl.component_count} ready
                      </span>
                      <span className="flex flex-wrap gap-1">
                        {tmpl.blocking_components.length === 0 ? (
                          <span className="text-xs text-muted-foreground">--</span>
                        ) : (
                          tmpl.blocking_components.map((bc) => (
                            <Badge
                              key={bc}
                              variant="destructive"
                              className="text-[10px] px-1.5 py-0"
                            >
                              {bc}
                            </Badge>
                          ))
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="edges">
            <EdgeInventoryTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
