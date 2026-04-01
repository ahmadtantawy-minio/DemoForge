import { useState, useEffect, useRef } from "react";
import { saveAsTemplate, overrideTemplate, fetchTemplates } from "../../api/client";
import type { DemoTemplate } from "../../types";
import { useDemoStore } from "../../stores/demoStore";
import { toast } from "sonner";
import { Loader2, AlertTriangle, ChevronDown, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface SaveAsTemplateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
  demoName?: string;
  demoDescription?: string;
  onSaved?: (templateId: string) => void;
}

const CATEGORIES = [
  { value: "infrastructure", label: "Infrastructure" },
  { value: "replication", label: "Replication" },
  { value: "analytics", label: "Analytics" },
  { value: "lakehouse", label: "Lakehouse" },
  { value: "ai", label: "AI" },
  { value: "simulation", label: "Simulation" },
  { value: "general", label: "General" },
];

export function SaveAsTemplateDialog({
  open,
  onOpenChange,
  demoId,
  demoName = "",
  demoDescription = "",
  onSaved,
}: SaveAsTemplateDialogProps) {
  const [mode, setMode] = useState<"new" | "override">("new");
  const [templateName, setTemplateName] = useState(demoName);
  const [description, setDescription] = useState(demoDescription);
  const [tier, setTier] = useState<"essentials" | "advanced">("advanced");
  const [category, setCategory] = useState("general");
  const [tags, setTags] = useState("");
  const [objective, setObjective] = useState("");
  const [minioValue, setMinioValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [overwrite, setOverwrite] = useState(false);

  // Override mode state
  const [existingTemplates, setExistingTemplates] = useState<DemoTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [templateSearch, setTemplateSearch] = useState("");
  const [templateDropdownOpen, setTemplateDropdownOpen] = useState(false);
  const templateComboboxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && mode === "override" && existingTemplates.length === 0) {
      fetchTemplates().then((res) => setExistingTemplates(res.templates)).catch(() => {});
    }
  }, [open, mode]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (templateComboboxRef.current && !templateComboboxRef.current.contains(e.target as Node)) {
        setTemplateDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function resetForm() {
    setMode("new");
    setTemplateName(demoName);
    setDescription(demoDescription);
    setTier("advanced");
    setCategory("general");
    setTags("");
    setObjective("");
    setMinioValue("");
    setSaving(false);
    setConflict(false);
    setOverwrite(false);
    setSelectedTemplateId("");
    setTemplateSearch("");
    setTemplateDropdownOpen(false);
  }

  function handleOpenChange(next: boolean) {
    if (!next) resetForm();
    onOpenChange(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (mode === "override") {
      if (!selectedTemplateId) return;
      setSaving(true);
      try {
        const result = await overrideTemplate(selectedTemplateId, demoId);
        toast.success("Template overridden", {
          description: `"${selectedTemplateId}" has been updated with this demo's state. The original was backed up.`,
        });
        onSaved?.(result.template_id);
        handleOpenChange(false);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        const isBackupFailure = msg.includes("aborted") || msg.includes("backup");
        toast.error(
          isBackupFailure
            ? "Override aborted — backup failed"
            : "Failed to override template",
          {
            description: isBackupFailure
              ? "The original template could not be safely backed up. No changes were made — your template is safe."
              : msg,
            duration: 15000,
          },
        );
      } finally {
        setSaving(false);
      }
      return;
    }

    if (!templateName.trim()) return;

    setSaving(true);
    setConflict(false);

    try {
      const result = await saveAsTemplate({
        demo_id: demoId,
        template_name: templateName.trim(),
        description: description.trim() || undefined,
        tier,
        category,
        tags: tags.trim()
          ? tags.split(",").map((t) => t.trim()).filter(Boolean)
          : undefined,
        objective: objective.trim() || undefined,
        minio_value: minioValue.trim() || undefined,
        overwrite: overwrite || undefined,
      });

      toast.success("Template saved", {
        description: result.message ?? `"${templateName}" is now available in the gallery.`,
      });

      onSaved?.(result.template_id);
      handleOpenChange(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("409")) {
        setConflict(true);
      } else {
        toast.error("Failed to save template", {
          description: msg,
        });
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-popover border-border text-foreground max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">Save as Template</DialogTitle>
          {demoName && (
            <p className="text-xs text-muted-foreground mt-0.5">
              Source: <span className="text-foreground/80">{demoName}</span>
            </p>
          )}
        </DialogHeader>

        <form onSubmit={handleSubmit} className="mt-2 space-y-4">
          {/* Mode toggle */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setMode("new")}
              className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                mode === "new"
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-border hover:text-foreground"
              }`}
            >
              New Template
            </button>
            <button
              type="button"
              onClick={() => setMode("override")}
              className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                mode === "override"
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-border hover:text-foreground"
              }`}
            >
              Override Existing
            </button>
          </div>

          {mode === "override" && (
            <>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Template to Override <span className="text-red-400">*</span>
                </label>
                <div ref={templateComboboxRef} className="relative">
                  <div
                    className="flex items-center h-8 rounded-md border border-border bg-background px-2 gap-1.5 cursor-pointer"
                    onClick={() => setTemplateDropdownOpen((v) => !v)}
                  >
                    <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                    <input
                      className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
                      placeholder={
                        selectedTemplateId
                          ? (existingTemplates.find((t) => t.id === selectedTemplateId)?.name ?? "Select a template...")
                          : "Search templates..."
                      }
                      value={templateDropdownOpen ? templateSearch : ""}
                      onChange={(e) => {
                        setTemplateSearch(e.target.value);
                        setTemplateDropdownOpen(true);
                      }}
                      onFocus={() => setTemplateDropdownOpen(true)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  </div>
                  {templateDropdownOpen && (
                    <div className="absolute z-50 mt-1 w-full rounded-md border border-border bg-popover shadow-md max-h-56 overflow-y-auto">
                      {existingTemplates
                        .filter((t) =>
                          !templateSearch ||
                          t.name.toLowerCase().includes(templateSearch.toLowerCase()) ||
                          t.id.toLowerCase().includes(templateSearch.toLowerCase())
                        )
                        .map((t) => (
                          <div
                            key={t.id}
                            className={`px-3 py-2 text-sm cursor-pointer hover:bg-accent hover:text-accent-foreground ${
                              t.id === selectedTemplateId ? "bg-accent/50 text-foreground" : "text-foreground"
                            }`}
                            onMouseDown={(e) => {
                              e.preventDefault();
                              setSelectedTemplateId(t.id);
                              setTemplateSearch("");
                              setTemplateDropdownOpen(false);
                            }}
                          >
                            <span className="font-medium">{t.name}</span>
                            <span className="ml-1.5 text-xs text-muted-foreground">({t.source})</span>
                          </div>
                        ))}
                      {existingTemplates.filter((t) =>
                        !templateSearch ||
                        t.name.toLowerCase().includes(templateSearch.toLowerCase()) ||
                        t.id.toLowerCase().includes(templateSearch.toLowerCase())
                      ).length === 0 && (
                        <div className="px-3 py-2 text-sm text-muted-foreground">No templates found</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-300 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>This will override the original template. The original will be backed up.</span>
              </div>
            </>
          )}

          {mode === "new" && (
          <>
          {/* Template Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Template Name <span className="text-red-400">*</span>
            </label>
            <Input
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              placeholder="e.g. My Replication Setup"
              className="bg-background border-border text-foreground placeholder:text-muted-foreground h-8 text-sm"
              required
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this template demonstrates"
              rows={2}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>

          {/* Tier + Category row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Tier
              </label>
              <Select value={tier} onValueChange={(v) => setTier(v as "essentials" | "advanced")}>
                <SelectTrigger className="bg-background border-border text-foreground h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-popover border-border text-foreground">
                  <SelectItem value="essentials">Essentials</SelectItem>
                  <SelectItem value="advanced">Advanced</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Category
              </label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger className="bg-background border-border text-foreground h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-popover border-border text-foreground">
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Tags */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Tags
              <span className="ml-1 normal-case text-muted-foreground/60">(comma-separated)</span>
            </label>
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g. s3, replication, multi-site"
              className="bg-background border-border text-foreground placeholder:text-muted-foreground h-8 text-sm"
            />
          </div>

          {/* Objective */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Objective
            </label>
            <textarea
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="What is the goal of this demo?"
              rows={2}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>

          {/* MinIO Value Proposition */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              MinIO Value Proposition
            </label>
            <textarea
              value={minioValue}
              onChange={(e) => setMinioValue(e.target.value)}
              placeholder="How does this demo highlight MinIO's value?"
              rows={2}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>

          </>
          )}

          {/* Conflict warning */}
          {conflict && mode === "new" && (
            <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 px-3 py-2.5 text-sm text-yellow-300">
              <p className="font-medium">A template with this name already exists.</p>
              <label className="mt-2 flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={overwrite}
                  onChange={(e) => setOverwrite(e.target.checked)}
                  className="h-3.5 w-3.5 accent-yellow-400"
                />
                <span className="text-xs text-yellow-200">Overwrite existing template</span>
              </label>
            </div>
          )}

          {/* FA attribution */}
          {useDemoStore.getState().faIdentified && (
            <p className="text-xs text-muted-foreground">
              Template will be saved as <span className="text-foreground/80">{useDemoStore.getState().faId}</span>
            </p>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleOpenChange(false)}
              disabled={saving}
              className="text-muted-foreground hover:text-foreground"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={saving || (mode === "new" ? (!templateName.trim() || (conflict && !overwrite)) : !selectedTemplateId)}
              className="min-w-[90px]"
            >
              {saving ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  Saving…
                </>
              ) : mode === "override" ? (
                "Override Template"
              ) : (
                "Save Template"
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
