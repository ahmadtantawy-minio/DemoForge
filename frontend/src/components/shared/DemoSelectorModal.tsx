import { useState, useEffect } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { createDemo, fetchDemos, deployDemo, stopDemo, deleteDemo } from "../../api/client";
import { toast } from "sonner";
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
import { Plus, Play, Square, Trash2, MoreVertical, LayoutTemplate } from "lucide-react";
import TemplateGallery from "../templates/TemplateGallery";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function DemoSelectorModal({ open, onOpenChange }: Props) {
  const { demos, activeDemoId, setActiveDemoId, setActiveView, setDemos } = useDemoStore();
  const [creating, setCreating] = useState(false);
  const [newDemoName, setNewDemoName] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [deleteOpts, setDeleteOpts] = useState({ destroyContainers: true, removeImages: false });

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
    setShowTemplates(false);
    onOpenChange(false);
  };

  const handleDeploy = async (e: React.MouseEvent, demoId: string) => {
    e.stopPropagation();
    try {
      toast.info("Deploying...");
      await deployDemo(demoId);
      const res = await fetchDemos();
      setDemos(res.demos);
      toast.success("Deploy started");
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
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col bg-popover border-border">
          <DialogHeader>
            <DialogTitle>Demo Manager</DialogTitle>
            <DialogDescription>Select, create, or manage your demos.</DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-2 pb-3 border-b border-border">
            {creating ? (
              <div className="flex items-center gap-2 flex-1">
                <Input
                  autoFocus
                  value={newDemoName}
                  onChange={(e) => setNewDemoName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreate();
                    if (e.key === "Escape") { setCreating(false); setNewDemoName(""); }
                  }}
                  placeholder="Demo name..."
                  className="h-8 text-sm flex-1"
                />
                <Button onClick={handleCreate} size="sm" className="h-8">Create</Button>
                <Button onClick={() => { setCreating(false); setNewDemoName(""); }} variant="ghost" size="sm" className="h-8">Cancel</Button>
              </div>
            ) : (
              <>
                <Button onClick={() => setCreating(true)} size="sm" className="gap-1.5 h-8 bg-primary text-primary-foreground hover:bg-primary/90">
                  <Plus className="w-3.5 h-3.5" />
                  New Demo
                </Button>
                <Button
                  variant={showTemplates ? "default" : "secondary"}
                  size="sm"
                  className="gap-1.5 h-8"
                  onClick={() => setShowTemplates(!showTemplates)}
                >
                  <LayoutTemplate className="w-3.5 h-3.5" />
                  From Template
                </Button>
              </>
            )}
          </div>

          {showTemplates && (
            <div className="border-b border-border pb-3">
              {/* Constrained height so the gallery never pushes the demo list off-screen */}
              <div className="max-h-[40vh] overflow-y-auto pr-1">
                <TemplateGallery onCreateDemo={handleCreateFromTemplate} />
              </div>
            </div>
          )}

          <div className="overflow-y-auto flex-1 min-h-0">
            {demos.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                No demos yet. Create one to get started.
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
                      {/* Status dot */}
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot[demo.status] ?? statusDot.stopped}`} />

                      {/* Demo info */}
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

                      {/* Actions — revealed on hover OR when focus lands inside (keyboard accessible) */}
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
          </div>
        </DialogContent>
      </Dialog>

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
