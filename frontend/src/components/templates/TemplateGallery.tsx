import { useState, useEffect } from "react";
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
import { Box, Cpu, MemoryStick, Container, Layers } from "lucide-react";

interface TemplateGalleryProps {
  onCreateDemo: (demoId: string) => void;
}

const categoryColors: Record<string, string> = {
  infrastructure: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  replication: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  analytics: "bg-green-500/15 text-green-400 border-green-500/30",
  ai: "bg-pink-500/15 text-pink-400 border-pink-500/30",
  general: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
};

export default function TemplateGallery({ onCreateDemo }: TemplateGalleryProps) {
  const [templates, setTemplates] = useState<DemoTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<DemoTemplateDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);

  // Editable fields in the detail dialog
  const [editDescription, setEditDescription] = useState("");
  const [editObjective, setEditObjective] = useState("");
  const [editMinioValue, setEditMinioValue] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    fetchTemplates()
      .then((res) => setTemplates(res.templates))
      .catch(() => {});
  }, []);

  const handleCardClick = async (templateId: string) => {
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
    }
  };

  const handleCreate = async (templateId: string) => {
    setCreating(templateId);
    try {
      const demo = await createFromTemplate(templateId);
      toast.success(`Demo "${demo.name}" created from template`);
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
      // Update in the list
      setTemplates((prev) =>
        prev.map((t) => (t.id === updated.id ? { ...t, ...updated } : t))
      );
      setSelectedTemplate((prev) => prev ? { ...prev, ...updated } : prev);
      setDirty(false);
      toast.success("Template updated");
    } catch (err: any) {
      toast.error("Failed to update template", { description: err.message });
    }
  };

  if (templates.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        No templates available.
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {templates.map((t) => (
          <div
            key={t.id}
            className="group border border-border rounded-lg bg-card hover:border-primary/50 hover:bg-accent/50 transition-all cursor-pointer flex flex-col"
            onClick={() => handleCardClick(t.id)}
          >
            {/* Card header */}
            <div className="p-4 flex-1">
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${categoryColors[t.category] ?? categoryColors.general}`}
                >
                  {t.category}
                </span>
              </div>
              <h3 className="font-semibold text-sm text-foreground mb-1">{t.name}</h3>
              <p className="text-xs text-muted-foreground line-clamp-3">{t.description}</p>

              {/* Tags */}
              {t.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-3">
                  {t.tags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-muted text-muted-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Card footer */}
            <div className="border-t border-border px-4 py-2.5 flex items-center justify-between">
              <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1" title="Containers">
                  <Container className="w-3 h-3" />
                  {t.container_count}
                </span>
                {t.estimated_resources.memory && (
                  <span className="flex items-center gap-1" title="Memory">
                    <MemoryStick className="w-3 h-3" />
                    {t.estimated_resources.memory}
                  </span>
                )}
                {t.estimated_resources.cpu && (
                  <span className="flex items-center gap-1" title="CPU cores">
                    <Cpu className="w-3 h-3" />
                    {t.estimated_resources.cpu} CPU
                  </span>
                )}
              </div>
              <Button
                size="sm"
                className="h-7 text-xs"
                disabled={creating === t.id}
                onClick={(e) => {
                  e.stopPropagation();
                  handleCreate(t.id);
                }}
              >
                {creating === t.id ? "Creating..." : "Create Demo"}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Template Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col bg-popover border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {selectedTemplate && (
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${categoryColors[selectedTemplate.category] ?? categoryColors.general}`}
                >
                  {selectedTemplate.category}
                </span>
              )}
              {selectedTemplate?.name}
            </DialogTitle>
          </DialogHeader>

          {selectedTemplate && (
            <div className="overflow-y-auto flex-1 space-y-4 pr-1">
              {/* Description (editable) */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">Description</label>
                <textarea
                  className="w-full bg-muted border border-border rounded-md px-3 py-2 text-sm text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                  rows={3}
                  value={editDescription}
                  onChange={(e) => { setEditDescription(e.target.value); setDirty(true); }}
                />
              </div>

              {/* Objective (editable) */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">Objective</label>
                <textarea
                  className="w-full bg-muted border border-border rounded-md px-3 py-2 text-sm text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                  rows={2}
                  value={editObjective}
                  onChange={(e) => { setEditObjective(e.target.value); setDirty(true); }}
                />
              </div>

              {/* MinIO Value Proposition */}
              <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                <label className="text-xs font-medium text-blue-400 block mb-1">MinIO Value Proposition</label>
                <textarea
                  className="w-full bg-transparent border-none text-sm text-blue-300 resize-none focus:outline-none"
                  rows={2}
                  value={editMinioValue}
                  onChange={(e) => { setEditMinioValue(e.target.value); setDirty(true); }}
                />
              </div>

              {dirty && (
                <div className="flex justify-end">
                  <Button size="sm" variant="secondary" onClick={handleSaveMetadata}>
                    Save Changes
                  </Button>
                </div>
              )}

              {/* Components */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-2">Components</label>
                <div className="flex flex-wrap gap-2">
                  {selectedTemplate.nodes.map((n: any) => (
                    <Badge key={n.id} variant="outline" className="text-xs">
                      <Layers className="w-3 h-3 mr-1" />
                      {n.display_name || n.component}
                    </Badge>
                  ))}
                  {selectedTemplate.clusters.map((c: any) => (
                    <Badge key={c.id} variant="outline" className="text-xs">
                      <Box className="w-3 h-3 mr-1" />
                      {c.label || c.component} ({c.node_count}x)
                    </Badge>
                  ))}
                </div>
              </div>

              {/* Walkthrough */}
              {selectedTemplate.walkthrough.length > 0 && (
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-2">Walkthrough</label>
                  <ol className="space-y-2">
                    {selectedTemplate.walkthrough.map((w, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/20 text-primary text-[10px] font-bold flex items-center justify-center mt-0.5">
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

              {/* Resource Summary */}
              <div className="flex items-center gap-4 text-xs text-muted-foreground pt-2 border-t border-border">
                <span className="flex items-center gap-1">
                  <Container className="w-3.5 h-3.5" />
                  {selectedTemplate.container_count} containers
                </span>
                {selectedTemplate.estimated_resources.memory && (
                  <span className="flex items-center gap-1">
                    <MemoryStick className="w-3.5 h-3.5" />
                    {selectedTemplate.estimated_resources.memory}
                  </span>
                )}
                {selectedTemplate.estimated_resources.cpu && (
                  <span className="flex items-center gap-1">
                    <Cpu className="w-3.5 h-3.5" />
                    {selectedTemplate.estimated_resources.cpu} CPU
                  </span>
                )}
              </div>

              {/* Create button */}
              <div className="flex justify-end pt-2">
                <Button
                  disabled={creating === selectedTemplate.id}
                  onClick={() => handleCreate(selectedTemplate.id)}
                >
                  {creating === selectedTemplate.id ? "Creating..." : "Create Demo"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
