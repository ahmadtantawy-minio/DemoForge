import { useState, useEffect, useMemo } from "react";
import { fetchTemplates, fetchTemplate, updateTemplate, createFromTemplate } from "../../api/client";
import type { DemoTemplate, DemoTemplateDetail } from "../../types";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Box, Cpu, MemoryStick, Container, Layers, Loader2, LayoutGrid, ListFilter } from "lucide-react";

interface TemplateGalleryProps {
  onCreateDemo: (demoId: string) => void;
}

const categoryColors: Record<string, string> = {
  infrastructure: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  replication:    "bg-purple-500/15 text-purple-400 border-purple-500/30",
  analytics:      "bg-green-500/15 text-green-400 border-green-500/30",
  lakehouse:      "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  ai:             "bg-pink-500/15 text-pink-400 border-pink-500/30",
  simulation:     "bg-violet-500/15 text-violet-400 border-violet-500/30",
  general:        "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
};

const tierLabels: Record<string, string> = {
  essentials: "Essentials",
  advanced: "Advanced",
  experience: "Experiences",
};

// Pill used both in cards and filter bar
function CategoryPill({
  category,
  active,
  onClick,
}: {
  category: string;
  active?: boolean;
  onClick?: () => void;
}) {
  const color = categoryColors[category] ?? categoryColors.general;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium border transition-all select-none
        ${color}
        ${active !== undefined
          ? active
            ? "opacity-100 ring-1 ring-current"
            : "opacity-50 hover:opacity-80"
          : "cursor-default"
        }`}
    >
      {category}
    </button>
  );
}

export default function TemplateGallery({ onCreateDemo }: TemplateGalleryProps) {
  const [templates, setTemplates] = useState<DemoTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<DemoTemplateDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [activeTier, setActiveTier] = useState<string>("essentials");

  // Editable fields in the detail dialog
  const [editDescription, setEditDescription] = useState("");
  const [editObjective, setEditObjective] = useState("");
  const [editMinioValue, setEditMinioValue] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setLoading(true);
    setLoadError(false);
    fetchTemplates()
      .then((res) => setTemplates(res.templates))
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  }, []);

  // Derive unique tiers
  const tiers = useMemo(() => {
    const seen = new Set<string>();
    templates.forEach((t) => seen.add(t.tier || "essentials"));
    return ["essentials", "advanced", "experience"].filter((t) => seen.has(t));
  }, [templates]);

  // Filter by tier first
  const tierFiltered = useMemo(
    () => templates.filter((t) => (t.tier || "essentials") === activeTier),
    [templates, activeTier]
  );

  // Derive unique categories within selected tier
  const categories = useMemo(() => {
    const seen = new Set<string>();
    tierFiltered.forEach((t) => seen.add(t.category));
    return Array.from(seen);
  }, [tierFiltered]);

  const filtered = useMemo(
    () => (activeCategory ? tierFiltered.filter((t) => t.category === activeCategory) : tierFiltered),
    [tierFiltered, activeCategory]
  );

  const handleCardClick = async (templateId: string) => {
    if (loadingDetail) return;
    setLoadingDetail(templateId);
    try {
      const detail = await fetchTemplate(templateId);
      setSelectedTemplate(detail);
      setEditDescription(detail.description);
      setEditObjective(detail.objective);
      setEditMinioValue(detail.minio_value);
      setDirty(false);
      setDetailOpen(true);
    } catch (err: any) {
      toast.error("Failed to load template details", { description: err.message });
    } finally {
      setLoadingDetail(null);
    }
  };

  const handleCreate = async (templateId: string) => {
    setCreating(templateId);
    try {
      const demo = await createFromTemplate(templateId);
      const isExp = selectedTemplate?.mode === "experience" || (selectedTemplate as any)?.mode === "experience";
      toast.success(
        isExp
          ? `Experience "${demo.name}" created — deploy and interact with the simulation`
          : `Demo "${demo.name}" created from template`
      );
      setDetailOpen(false);
      onCreateDemo(demo.id);
    } catch (err: any) {
      toast.error("Failed to create demo from template", { description: err.message });
    } finally {
      setCreating(null);
    }
  };

  const handleSaveMetadata = async () => {
    if (!selectedTemplate) return;
    try {
      const updated = await updateTemplate(selectedTemplate.id, {
        description: editDescription,
        objective: editObjective,
        minio_value: editMinioValue,
      });
      setTemplates((prev) =>
        prev.map((t) => (t.id === updated.id ? { ...t, ...updated } : t))
      );
      setSelectedTemplate((prev) => (prev ? { ...prev, ...updated } : prev));
      setDirty(false);
      toast.success("Template updated");
    } catch (err: any) {
      toast.error("Failed to update template", { description: err.message });
    }
  };

  // ── Loading skeleton ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="space-y-4 pt-2">
        <div className="flex items-center gap-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-6 w-20 rounded-full bg-muted animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div
              key={i}
              className="border border-border rounded-lg bg-card flex flex-col gap-3 p-4 animate-pulse"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <div className="h-4 w-20 rounded-full bg-muted" />
              <div className="h-5 w-3/4 rounded bg-muted" />
              <div className="space-y-1.5">
                <div className="h-3 w-full rounded bg-muted" />
                <div className="h-3 w-5/6 rounded bg-muted" />
                <div className="h-3 w-2/3 rounded bg-muted" />
              </div>
              <div className="flex gap-1 mt-1">
                <div className="h-4 w-14 rounded bg-muted" />
                <div className="h-4 w-10 rounded bg-muted" />
              </div>
              <div className="border-t border-border pt-2.5 flex justify-between items-center">
                <div className="flex gap-3">
                  <div className="h-3 w-8 rounded bg-muted" />
                  <div className="h-3 w-10 rounded bg-muted" />
                </div>
                <div className="h-7 w-24 rounded bg-muted" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────
  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
        <div className="w-12 h-12 rounded-xl bg-destructive/10 flex items-center justify-center mb-1">
          <LayoutGrid className="w-6 h-6 text-destructive/70" />
        </div>
        <p className="text-sm font-medium text-foreground">Failed to load templates</p>
        <p className="text-xs text-muted-foreground max-w-[280px]">
          Could not reach the template API. Check your server and try again.
        </p>
        <button
          type="button"
          className="text-xs text-primary hover:underline underline-offset-2 mt-1"
          onClick={() => {
            setLoadError(false);
            setLoading(true);
            fetchTemplates()
              .then((res) => setTemplates(res.templates))
              .catch(() => setLoadError(true))
              .finally(() => setLoading(false));
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  // ── Empty state ──────────────────────────────────────────────────────
  if (templates.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
        <div className="w-12 h-12 rounded-xl bg-muted flex items-center justify-center mb-1">
          <LayoutGrid className="w-6 h-6 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium text-foreground">No templates available</p>
        <p className="text-xs text-muted-foreground max-w-[280px]">
          Templates will appear here once they are added to the backend. Check your server configuration.
        </p>
      </div>
    );
  }

  // ── Empty filtered state ─────────────────────────────────────────────
  const emptyFilter = filtered.length === 0 && activeCategory !== null;

  return (
    <>
      {/* ── Tier tabs ─────────────────────────────────────────────── */}
      {tiers.length > 1 && (
        <div className="flex items-center gap-1 mb-3" role="tablist" aria-label="Template tiers">
          {tiers.map((tier) => {
            const count = templates.filter((t) => (t.tier || "essentials") === tier).length;
            return (
              <button
                key={tier}
                role="tab"
                aria-selected={activeTier === tier}
                data-testid={`tier-tab-${tier === "experience" ? "experiences" : tier}`}
                onClick={() => { setActiveTier(tier); setActiveCategory(null); }}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all select-none
                  ${activeTier === tier
                    ? "bg-primary/15 text-primary border border-primary/30"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50 border border-transparent"
                  }`}
              >
                {tierLabels[tier] || tier} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* ── Category filter bar ─────────────────────────────────────── */}
      {categories.length > 1 && (
        <div
          className="flex items-center gap-2 flex-wrap mb-4 pb-3 border-b border-border"
          role="group"
          aria-label="Filter templates by category"
        >
          <ListFilter className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
          <button
            type="button"
            onClick={() => setActiveCategory(null)}
            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium border transition-all select-none
              border-border text-muted-foreground
              ${activeCategory === null
                ? "bg-muted opacity-100 ring-1 ring-border"
                : "opacity-60 hover:opacity-90 hover:bg-muted/50"
              }`}
          >
            All ({tierFiltered.length})
          </button>
          {categories.map((cat) => (
            <CategoryPill
              key={cat}
              category={cat}
              active={activeCategory === cat}
              onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
            />
          ))}
        </div>
      )}

      {emptyFilter ? (
        <div className="flex flex-col items-center justify-center py-16 gap-2 text-center">
          <p className="text-sm text-muted-foreground">
            No templates in the <span className="text-foreground font-medium">{activeCategory}</span> category.
          </p>
          <button
            type="button"
            className="text-xs text-primary hover:underline underline-offset-2"
            onClick={() => setActiveCategory(null)}
          >
            Clear filter
          </button>
        </div>
      ) : (
        <div
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
          role="list"
          aria-label="Template gallery"
        >
          {filtered.map((t) => (
            <div
              key={t.id}
              role="listitem"
              tabIndex={0}
              aria-label={`${t.name} template, ${t.category} category`}
              aria-busy={loadingDetail === t.id}
              className={`group border border-border rounded-lg bg-card hover:border-primary/40 hover:bg-accent/30 hover:shadow-sm transition-all duration-150 flex flex-col focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card ${loadingDetail === t.id ? "opacity-70 cursor-wait" : "cursor-pointer"}`}
              onClick={() => handleCardClick(t.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleCardClick(t.id);
                }
              }}
            >
              {/* Card body */}
              <div className="p-4 flex-1 flex flex-col gap-2">
                {/* Category + resource hint row */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <CategoryPill category={t.category} />
                    {(t as any).mode === "experience" && (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-violet-500/20 text-violet-300 border border-violet-500/30" data-testid="experience-badge">
                        Experience
                      </span>
                    )}
                    {t.has_se_guide && (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-teal-500/15 text-teal-400 border border-teal-500/30" data-testid="se-guide-indicator">
                        SE Guide
                      </span>
                    )}
                  </div>
                  <span
                    className="text-[10px] text-muted-foreground flex items-center gap-1"
                    title={`${t.container_count} container${t.container_count !== 1 ? "s" : ""}`}
                  >
                    <Container className="w-3 h-3" aria-hidden="true" />
                    {t.container_count}
                  </span>
                </div>

                {/* Name — primary attention target */}
                <h3 className="font-semibold text-base text-foreground leading-snug group-hover:text-primary transition-colors duration-150">
                  {t.name}
                </h3>

                {/* Description */}
                <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
                  {t.description}
                </p>

                {/* Tags */}
                {t.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-auto pt-2">
                    {t.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-muted/80 text-muted-foreground border border-border/60"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Card footer */}
              <div className="border-t border-border px-4 py-2.5 flex items-center justify-between gap-2 bg-muted/20 rounded-b-lg">
                <div
                  className="flex items-center gap-3 text-[10px] text-muted-foreground"
                  aria-label="Resource requirements"
                >
                  {t.estimated_resources.memory && (
                    <span className="flex items-center gap-1" title="Estimated memory">
                      <MemoryStick className="w-3 h-3" aria-hidden="true" />
                      {t.estimated_resources.memory}
                    </span>
                  )}
                  {t.estimated_resources.cpu && (
                    <span className="flex items-center gap-1" title="Estimated CPU">
                      <Cpu className="w-3 h-3" aria-hidden="true" />
                      {t.estimated_resources.cpu} CPU
                    </span>
                  )}
                </div>
                <Button
                  size="sm"
                  className="h-7 text-xs shrink-0"
                  disabled={creating === t.id || !!loadingDetail}
                  aria-label={`Create demo from template: ${t.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCreate(t.id);
                  }}
                >
                  {creating === t.id ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin mr-1" aria-hidden="true" />
                      Creating…
                    </>
                  ) : loadingDetail === t.id ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin mr-1" aria-hidden="true" />
                      Loading…
                    </>
                  ) : (
                    "Create Demo"
                  )}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Template Detail Dialog ───────────────────────────────────── */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col bg-popover border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              {selectedTemplate && (
                <CategoryPill category={selectedTemplate.category} />
              )}
              <span className="font-semibold">{selectedTemplate?.name}</span>
            </DialogTitle>
          </DialogHeader>

          {selectedTemplate && (
            <>
              {/* Scrollable content region */}
              <div className="overflow-y-auto flex-1 space-y-4 pr-3 min-h-0">
                {/* Description (editable) */}
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    Description
                  </label>
                  <textarea
                    className="w-full bg-muted border border-border rounded-md px-3 py-2 text-sm text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                    rows={3}
                    value={editDescription}
                    onChange={(e) => { setEditDescription(e.target.value); setDirty(true); }}
                  />
                </div>

                {/* Objective (editable) */}
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    Objective
                  </label>
                  <textarea
                    className="w-full bg-muted border border-border rounded-md px-3 py-2 text-sm text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                    rows={2}
                    value={editObjective}
                    onChange={(e) => { setEditObjective(e.target.value); setDirty(true); }}
                  />
                </div>

                {/* MinIO Value Proposition — editable field with visible affordance */}
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                  <label className="text-xs font-medium text-blue-400 block mb-1">
                    MinIO Value Proposition
                  </label>
                  <textarea
                    className="w-full bg-transparent border border-blue-500/20 rounded text-sm text-blue-300 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50 px-2 py-1"
                    rows={2}
                    value={editMinioValue}
                    onChange={(e) => { setEditMinioValue(e.target.value); setDirty(true); }}
                  />
                </div>

                {/* Unsaved changes indicator + save */}
                {dirty && (
                  <div className="flex items-center justify-between rounded-md border border-yellow-500/30 bg-yellow-500/5 px-3 py-2">
                    <span className="text-xs text-yellow-400">Unsaved changes</span>
                    <Button size="sm" variant="secondary" onClick={handleSaveMetadata}>
                      Save Changes
                    </Button>
                  </div>
                )}

                {/* Components */}
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-2">
                    Components
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {selectedTemplate.nodes.map((n: any) => (
                      <Badge key={n.id} variant="outline" className="text-xs">
                        <Layers className="w-3 h-3 mr-1" aria-hidden="true" />
                        {n.display_name || n.component}
                      </Badge>
                    ))}
                    {selectedTemplate.clusters.map((c: any) => (
                      <Badge key={c.id} variant="outline" className="text-xs">
                        <Box className="w-3 h-3 mr-1" aria-hidden="true" />
                        {c.label || c.component} ({c.node_count}x)
                      </Badge>
                    ))}
                  </div>
                </div>

                {/* Walkthrough */}
                {selectedTemplate.walkthrough.length > 0 && (
                  <div>
                    <label className="text-xs font-medium text-muted-foreground block mb-2">
                      Walkthrough
                    </label>
                    <ol className="space-y-2" aria-label="Demo walkthrough steps">
                      {selectedTemplate.walkthrough.map((w, i) => (
                        <li key={`${selectedTemplate.id}-step-${i}`} className="flex gap-3">
                          <span
                            className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/20 text-primary text-[10px] font-bold flex items-center justify-center mt-0.5"
                            aria-hidden="true"
                          >
                            {i + 1}
                          </span>
                          <div>
                            <div className="text-sm font-medium text-foreground">{w.step}</div>
                            <div className="text-xs text-muted-foreground">{w.description}</div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>

              {/* Pinned footer — always visible, never scrolls away */}
              <div className="flex items-center justify-between pt-3 border-t border-border flex-shrink-0">
                <div
                  className="flex items-center gap-4 text-xs text-muted-foreground"
                  aria-label="Resource summary"
                >
                  <span className="flex items-center gap-1">
                    <Container className="w-3.5 h-3.5" aria-hidden="true" />
                    {selectedTemplate.container_count} container{selectedTemplate.container_count !== 1 ? "s" : ""}
                  </span>
                  {selectedTemplate.estimated_resources.memory && (
                    <span className="flex items-center gap-1">
                      <MemoryStick className="w-3.5 h-3.5" aria-hidden="true" />
                      {selectedTemplate.estimated_resources.memory}
                    </span>
                  )}
                  {selectedTemplate.estimated_resources.cpu && (
                    <span className="flex items-center gap-1">
                      <Cpu className="w-3.5 h-3.5" aria-hidden="true" />
                      {selectedTemplate.estimated_resources.cpu} CPU
                    </span>
                  )}
                </div>

                <Button
                  disabled={creating === selectedTemplate.id}
                  aria-label={`Create demo from template: ${selectedTemplate.name}`}
                  onClick={() => handleCreate(selectedTemplate.id)}
                >
                  {creating === selectedTemplate.id ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin mr-1" aria-hidden="true" />
                      Creating…
                    </>
                  ) : (
                    "Create Demo"
                  )}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
