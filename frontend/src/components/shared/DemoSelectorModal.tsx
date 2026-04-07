import { useState, useEffect, useRef } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { createDemo, fetchDemos, deployDemo, stopDemo, deleteDemo, exportDemo, importDemo } from "../../api/client";
import { toast } from "../../lib/toast";
import { usePermissions } from "../../hooks/usePermissions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Plus, Play, Square, Trash2, MoreVertical, LayoutTemplate, FolderOpen, Upload, Download } from "lucide-react";
import TemplateGallery from "../templates/TemplateGallery";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function DemoSelectorModal({ open, onOpenChange }: Props) {
  const { demos, activeDemoId, setActiveDemoId, setActiveView, setDemos } = useDemoStore();
  const { permissions } = usePermissions();
  const [creating, setCreating] = useState(false);
  const [newDemoName, setNewDemoName] = useState("");
  const [activeTab, setActiveTab] = useState<"demos" | "templates">("demos");
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [deleteOpts, setDeleteOpts] = useState({ destroyContainers: true, removeImages: false });
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await importDemo(file);
      const res = await fetchDemos();
      setDemos(res.demos);
      toast.success(`Demo "${result.name}" imported`);
    } catch (err: any) {
      toast.error("Import failed", { description: err.message });
    }
    e.target.value = '';
  };

  useEffect(() => {
    if (open) {
      fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
    }
  }, [open]);

  const handleSelect = (demoId: string) => {
    setActiveDemoId(demoId);
    setActiveView("diagram");
    onOpenChange(false);
  };

  const handleCreate = async () => {
    if (!newDemoName.trim()) return;
    try {
      const demo = await createDemo(newDemoName.trim());
      const res = await fetchDemos();
      setDemos(res.demos);
      setActiveDemoId(demo.id);
      setActiveView("diagram");
      setCreating(false);
      setNewDemoName("");
      onOpenChange(false);
      toast.success(`Demo "${newDemoName.trim()}" created`);
    } catch (err: any) {
      toast.error("Failed to create demo", { description: err.message });
    }
  };

  const handleCreateFromTemplate = (demoId: string) => {
    fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
    setActiveDemoId(demoId);
    setActiveView("diagram");
    setActiveTab("demos");
    onOpenChange(false);
  };

  const handleDeploy = async (e: React.MouseEvent, demoId: string) => {
    e.stopPropagation();
    try {
      await deployDemo(demoId);
      const res = await fetchDemos();
      setDemos(res.demos);
    } catch (err: any) {
      toast.error("Deploy failed", { description: err.message });
    }
  };

  const handleStop = async (e: React.MouseEvent, demoId: string) => {
    e.stopPropagation();
    try {
      await stopDemo(demoId);
      const res = await fetchDemos();
      setDemos(res.demos);
      toast.success("Demo stopped");
    } catch (err: any) {
      toast.error("Stop failed", { description: err.message });
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteDemo(deleteTarget.id, deleteOpts);
      if (activeDemoId === deleteTarget.id) {
        setActiveDemoId(null);
      }
      const res = await fetchDemos();
      setDemos(res.demos);
      toast.success(`Demo "${deleteTarget.name}" deleted`);
    } catch (err: any) {
      toast.error("Delete failed", { description: err.message });
    } finally {
      setDeleteTarget(null);
      setDeleteOpts({ destroyContainers: true, removeImages: false });
    }
  };

  const statusColors: Record<string, string> = {
    running: "bg-green-500/20 text-green-400 border-green-500/40",
    deploying: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
    error: "bg-red-500/20 text-red-400 border-red-500/40",
    stopped: "bg-zinc-500/20 text-zinc-400 border-zinc-500/40",
  };

  const statusDot: Record<string, string> = {
    running: "bg-green-400",
    deploying: "bg-yellow-400 animate-pulse",
    error: "bg-red-400",
    stopped: "bg-zinc-500",
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col bg-popover border-border">
          <DialogHeader>
            <DialogTitle>Demo Manager</DialogTitle>
            <DialogDescription>Create demos from templates or manage your existing ones.</DialogDescription>
          </DialogHeader>

          {/* Tab bar */}
          <div className="flex items-center gap-1 border-b border-border">
            <button
              onClick={() => setActiveTab("demos")}
              className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "demos"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
              }`}
            >
              <FolderOpen className="w-4 h-4" />
              My Demos
              {demos.length > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-medium">
                  {demos.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("templates")}
              className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "templates"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
              }`}
            >
              <LayoutTemplate className="w-4 h-4" />
              Templates
            </button>

            {/* New Demo button — always visible on the right */}
            <div className="ml-auto pb-1">
              {creating ? (
                <div className="flex items-center gap-2">
                  <Input
                    autoFocus
                    value={newDemoName}
                    onChange={(e) => setNewDemoName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleCreate();
                      if (e.key === "Escape") { setCreating(false); setNewDemoName(""); }
                    }}
                    placeholder="Demo name..."
                    className="h-7 text-xs w-44"
                  />
                  <Button onClick={handleCreate} size="sm" className="h-7 text-xs">Create</Button>
                  <Button onClick={() => { setCreating(false); setNewDemoName(""); }} variant="ghost" size="sm" className="h-7 text-xs">Cancel</Button>
                </div>
              ) : (
                <div className="flex items-center gap-1.5">
                  <Button onClick={() => fileInputRef.current?.click()} size="sm" variant="outline" className="gap-1.5 h-7 text-xs">
                    <Upload className="w-3.5 h-3.5" />
                    Import
                  </Button>
                  <Button onClick={() => setCreating(true)} size="sm" className="gap-1.5 h-7 text-xs" disabled={!permissions.manual_demo_creation}>
                    <Plus className="w-3.5 h-3.5" />
                    New Blank Demo
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* Tab content */}
          <div className="overflow-y-auto flex-1 min-h-0">
            {/* ── My Demos tab ── */}
            {activeTab === "demos" && (
              <>
                {demos.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
                    <FolderOpen className="w-10 h-10 text-muted-foreground/50" />
                    <p className="text-sm text-muted-foreground">No demos yet.</p>
                    <p className="text-xs text-muted-foreground">Create a blank demo or pick one from the <button className="text-primary hover:underline underline-offset-2" onClick={() => setActiveTab("templates")}>Templates</button> tab.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-2 py-2">
                    {demos.map((demo) => (
                      <button
                        key={demo.id}
                        onClick={() => handleSelect(demo.id)}
                        className={`text-left px-4 py-3 rounded-lg border transition-all cursor-pointer group ${
                          activeDemoId === demo.id
                            ? "border-primary bg-primary/5 shadow-md"
                            : "border-border bg-card hover:border-primary/50 hover:bg-accent"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot[demo.status] ?? statusDot.stopped}`} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-sm text-foreground truncate">{demo.name}</span>
                              {activeDemoId === demo.id && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary font-medium">current</span>
                              )}
                              <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${statusColors[demo.status] ?? statusColors.stopped}`}>
                                {demo.status}
                              </span>
                            </div>
                            {demo.description && (
                              <p className="text-xs text-muted-foreground mt-0.5 truncate">{demo.description}</p>
                            )}
                            <div className="flex items-center gap-3 text-[10px] text-zinc-500 mt-1">
                              <span>{demo.node_count} node{demo.node_count !== 1 ? "s" : ""}</span>
                              <span className="font-mono">{demo.id}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                            {demo.status === "stopped" || demo.status === "error" ? (
                              <Button
                                size="sm"
                                className="h-7 w-7 p-0 bg-green-600 hover:bg-green-500 text-white"
                                onClick={(e) => handleDeploy(e, demo.id)}
                                title="Deploy"
                              >
                                <Play className="w-3.5 h-3.5" />
                              </Button>
                            ) : demo.status === "running" ? (
                              <Button
                                size="sm"
                                variant="destructive"
                                className="h-7 w-7 p-0"
                                onClick={(e) => handleStop(e, demo.id)}
                                title="Stop"
                              >
                                <Square className="w-3.5 h-3.5" />
                              </Button>
                            ) : null}
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-zinc-400 hover:text-foreground">
                                  <MoreVertical className="w-3.5 h-3.5" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-40">
                                <DropdownMenuItem onSelect={() => handleSelect(demo.id)}>
                                  Open
                                </DropdownMenuItem>
                                {(demo.status === "stopped" || demo.status === "error") && (
                                  <DropdownMenuItem onSelect={(e) => { handleDeploy(e as any, demo.id); }}>
                                    Deploy
                                  </DropdownMenuItem>
                                )}
                                {demo.status === "running" && (
                                  <DropdownMenuItem onSelect={(e) => { handleStop(e as any, demo.id); }}>
                                    Stop
                                  </DropdownMenuItem>
                                )}
                                <DropdownMenuItem onSelect={() => exportDemo(demo.id)}>
                                  <Download className="w-3.5 h-3.5 mr-2" />
                                  Export
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  className="text-red-400 focus:text-red-400"
                                  onSelect={() => setDeleteTarget({ id: demo.id, name: demo.name })}
                                >
                                  <Trash2 className="w-3.5 h-3.5 mr-2" />
                                  Delete
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}

            {/* ── Templates tab ── */}
            {activeTab === "templates" && (
              <div className="py-2">
                <TemplateGallery onCreateDemo={handleCreateFromTemplate} />
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <input ref={fileInputRef} type="file" accept=".yaml,.yml" className="hidden" onChange={handleImport} />

      {/* Delete confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{deleteTarget?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the demo configuration.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 py-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={deleteOpts.destroyContainers}
                onChange={(e) => setDeleteOpts((o) => ({ ...o, destroyContainers: e.target.checked }))}
                className="rounded"
              />
              Also destroy containers
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={deleteOpts.removeImages}
                onChange={(e) => setDeleteOpts((o) => ({ ...o, removeImages: e.target.checked }))}
                className="rounded"
              />
              Also remove Docker images
            </label>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-600 hover:bg-red-500 text-white">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
