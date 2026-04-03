import { useEffect, useState, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { useDebugStore } from "../../stores/debugStore";
import {
  fetchDemos, fetchInventory, deleteDemo, deployDemo, stopDemo,
  createDemo,
} from "../../api/client";
import { toast } from "../../lib/toast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import DeployProgress from "../deploy/DeployProgress";
import TemplateGallery from "../templates/TemplateGallery";

interface InventoryContainer {
  id: string; name: string; image: string; status: string;
  demo_id: string; node_id: string; component: string; created: string;
}

interface InventoryImage {
  id: string; tags: string[]; size_mb: number; created: string;
}

export default function DemoManager() {
  const { demos, activeDemoId, setDemos, setActiveDemoId, setActiveView, updateDemoStatus } = useDemoStore();
  const debugStore = useDebugStore();

  const [containers, setContainers] = useState<InventoryContainer[]>([]);
  const [images, setImages] = useState<InventoryImage[]>([]);
  const [creating, setCreating] = useState(false);
  const [newDemoName, setNewDemoName] = useState("");
  const [loading, setLoading] = useState<Record<string, string>>({});

  // Deploy progress state
  const [deployingDemo, setDeployingDemo] = useState<{ id: string; name: string } | null>(null);

  // Delete dialog state
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [deleteOpts, setDeleteOpts] = useState({ destroyContainers: true, removeImages: false });

  const refreshDemos = useCallback(() => {
    fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
  }, [setDemos]);

  const refreshInventory = useCallback(() => {
    fetchInventory()
      .then((res) => {
        setContainers(res.containers);
        setImages(res.images);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshDemos();
    refreshInventory();
    const interval = setInterval(() => {
      refreshDemos();
      refreshInventory();
    }, 5000);
    return () => clearInterval(interval);
  }, [refreshDemos, refreshInventory]);

  const handleCreate = async () => {
    if (!newDemoName.trim()) return;
    try {
      await createDemo(newDemoName.trim());
      refreshDemos();
      setCreating(false);
      setNewDemoName("");
      toast.success(`Demo "${newDemoName.trim()}" created`);
    } catch (err: any) {
      toast.error("Failed to create demo", { description: err.message });
    }
  };

  const handleCreateFromTemplate = (demoId: string) => {
    refreshDemos();
    setActiveDemoId(demoId);
    setActiveView("diagram");
  };

  const handleDeploy = (demoId: string) => {
    const demo = demos.find((d) => d.id === demoId);
    updateDemoStatus(demoId, "deploying");
    setDeployingDemo({ id: demoId, name: demo?.name ?? demoId });
    deployDemo(demoId).catch(() => {});
  };

  const handleDeployDone = (success: boolean) => {
    if (deployingDemo) {
      updateDemoStatus(deployingDemo.id, success ? "running" : "error");
    }
    setDeployingDemo(null);
    refreshDemos();
    refreshInventory();
  };

  const handleStop = async (demoId: string) => {
    setLoading((l) => ({ ...l, [demoId]: "stop" }));
    try {
      await stopDemo(demoId);
      updateDemoStatus(demoId, "stopped");
      toast.success("Demo stopped");
    } catch (err: any) {
      debugStore.addEntry("error", "Deploy", `Stop failed`, err.message);
      toast.error("Failed to stop demo", { description: err.message });
    } finally {
      setLoading((l) => { const n = { ...l }; delete n[demoId]; return n; });
      refreshInventory();
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setLoading((l) => ({ ...l, [deleteTarget.id]: "delete" }));
    try {
      await deleteDemo(deleteTarget.id, {
        destroyContainers: deleteOpts.destroyContainers,
        removeImages: deleteOpts.removeImages,
      });
      debugStore.addEntry("info", "Admin", `Deleted demo "${deleteTarget.name}"`);
      toast.success(`Demo "${deleteTarget.name}" deleted`);
      if (activeDemoId === deleteTarget.id) setActiveDemoId(null);
      refreshDemos();
      refreshInventory();
    } catch (err: any) {
      debugStore.addEntry("error", "Admin", `Delete failed`, err.message);
      toast.error("Failed to delete demo", { description: err.message });
    } finally {
      setLoading((l) => { const n = { ...l }; delete n[deleteTarget.id]; return n; });
      setDeleteTarget(null);
    }
  };

  const openDemo = (demoId: string) => {
    setActiveDemoId(demoId);
    setActiveView("diagram");
  };

  const statusBadge = (status: string) => {
    const variants: Record<string, string> = {
      running: "bg-green-500/15 text-green-400 border-green-500/30",
      deploying: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
      error: "bg-red-500/15 text-red-400 border-red-500/30",
      stopped: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
    };
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${variants[status] ?? variants.stopped}`}>
        <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${status === "running" ? "bg-green-400" : status === "deploying" ? "bg-yellow-400 animate-pulse" : status === "error" ? "bg-red-400" : "bg-zinc-500"}`} />
        {status}
      </span>
    );
  };

  const containerStatusBadge = (status: string) => {
    const color = status === "running" ? "text-green-400" : status === "exited" ? "text-zinc-400" : "text-yellow-400";
    return <span className={`text-xs font-mono ${color}`}>{status}</span>;
  };

  const demoContainerCount = (demoId: string) =>
    containers.filter((c) => c.demo_id === demoId).length;

  return (
    <div className="w-full h-full bg-background overflow-auto">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-foreground">Demo Management</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {demos.length} demo{demos.length !== 1 ? "s" : ""} &middot; {containers.length} container{containers.length !== 1 ? "s" : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {creating ? (
              <div className="flex items-center gap-2">
                <Input
                  autoFocus
                  value={newDemoName}
                  onChange={(e) => setNewDemoName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreate();
                    if (e.key === "Escape") setCreating(false);
                  }}
                  placeholder="Demo name..."
                  className="h-9 text-sm w-48"
                />
                <Button onClick={handleCreate} size="sm">Create</Button>
                <Button onClick={() => setCreating(false)} variant="ghost" size="sm">Cancel</Button>
              </div>
            ) : (
              <>
                <Button onClick={() => setCreating(true)} size="sm">
                  + New Demo
                </Button>
              </>
            )}
          </div>
        </div>

        <Tabs defaultValue="demos">
          <TabsList>
            <TabsTrigger value="demos">Demos</TabsTrigger>
            <TabsTrigger value="templates">Templates</TabsTrigger>
            <TabsTrigger value="containers">Containers ({containers.length})</TabsTrigger>
            <TabsTrigger value="images">Images ({images.length})</TabsTrigger>
          </TabsList>

          {/* === DEMOS TAB === */}
          <TabsContent value="demos">
            {demos.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center">
                  <p className="text-muted-foreground text-sm">No demos yet. Create one to get started.</p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-2">
                {demos.map((demo) => {
                  const isActive = demo.id === activeDemoId;
                  const containerCount = demoContainerCount(demo.id);
                  const demoLoading = loading[demo.id];

                  return (
                    <Card
                      key={demo.id}
                      className={`transition-colors ${isActive ? "border-primary/50 bg-card" : "bg-card/50 hover:bg-card"}`}
                    >
                      <CardContent className="py-3 px-4">
                        <div className="flex items-center gap-4">
                          {/* Info */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => openDemo(demo.id)}
                                className="font-medium text-sm text-foreground hover:text-primary transition-colors truncate"
                              >
                                {demo.name}
                              </button>
                              {statusBadge(demo.status)}
                              {isActive && (
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0">active</Badge>
                              )}
                            </div>
                            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                              <span className="font-mono truncate max-w-[120px]" title={demo.id}>{demo.id}</span>
                              <span>{demo.node_count} node{demo.node_count !== 1 ? "s" : ""}</span>
                              {containerCount > 0 && (
                                <span>{containerCount} container{containerCount !== 1 ? "s" : ""}</span>
                              )}
                              {demo.description && (
                                <span className="truncate max-w-[200px]">{demo.description}</span>
                              )}
                            </div>
                          </div>

                          {/* Actions */}
                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            <Button
                              variant="ghost"
                              size="xs"
                              onClick={() => openDemo(demo.id)}
                            >
                              Open
                            </Button>

                            {(demo.status === "stopped" || demo.status === "error") && (
                              <Button
                                size="xs"
                                className="bg-green-600 hover:bg-green-500 text-white"
                                disabled={!!demoLoading}
                                onClick={() => handleDeploy(demo.id)}
                              >
                                {demoLoading === "deploy" ? "Deploying..." : "Deploy"}
                              </Button>
                            )}

                            {demo.status === "running" && (
                              <Button
                                variant="destructive"
                                size="xs"
                                disabled={!!demoLoading}
                                onClick={() => handleStop(demo.id)}
                              >
                                {demoLoading === "stop" ? "Stopping..." : "Stop"}
                              </Button>
                            )}

                            {demo.status === "deploying" && (
                              <Badge variant="outline" className="text-yellow-400 border-yellow-500/30 text-[10px]">
                                deploying...
                              </Badge>
                            )}

                            <Button
                              variant="ghost"
                              size="xs"
                              className="text-destructive hover:text-destructive hover:bg-destructive/10"
                              disabled={!!demoLoading}
                              onClick={() => {
                                setDeleteTarget({ id: demo.id, name: demo.name });
                                setDeleteOpts({
                                  destroyContainers: demo.status === "running",
                                  removeImages: false,
                                });
                              }}
                            >
                              Delete
                            </Button>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </TabsContent>

          {/* === TEMPLATES TAB === */}
          <TabsContent value="templates" className="pt-2">
            <TemplateGallery onCreateDemo={handleCreateFromTemplate} />
          </TabsContent>

          {/* === CONTAINERS TAB === */}
          <TabsContent value="containers">
            {containers.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center">
                  <p className="text-muted-foreground text-sm">No DemoForge containers running.</p>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted-foreground">
                        <th className="px-4 py-2 font-medium">Container</th>
                        <th className="px-4 py-2 font-medium">Image</th>
                        <th className="px-4 py-2 font-medium">Status</th>
                        <th className="px-4 py-2 font-medium">Demo</th>
                        <th className="px-4 py-2 font-medium">Component</th>
                      </tr>
                    </thead>
                    <tbody>
                      {containers.map((c) => {
                        const demoName = demos.find((d) => d.id === c.demo_id)?.name ?? c.demo_id;
                        return (
                          <tr key={c.id} className="border-b border-border/50 hover:bg-muted/50">
                            <td className="px-4 py-2">
                              <div className="font-mono text-xs text-foreground">{c.name}</div>
                              <div className="font-mono text-[10px] text-muted-foreground">{c.id}</div>
                            </td>
                            <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{c.image}</td>
                            <td className="px-4 py-2">{containerStatusBadge(c.status)}</td>
                            <td className="px-4 py-2">
                              <button
                                onClick={() => openDemo(c.demo_id)}
                                className="text-xs text-primary hover:underline"
                              >
                                {demoName}
                              </button>
                            </td>
                            <td className="px-4 py-2 text-xs text-muted-foreground">{c.component}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* === IMAGES TAB === */}
          <TabsContent value="images">
            {images.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center">
                  <p className="text-muted-foreground text-sm">No Docker images found.</p>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted-foreground">
                        <th className="px-4 py-2 font-medium">Image</th>
                        <th className="px-4 py-2 font-medium">ID</th>
                        <th className="px-4 py-2 font-medium text-right">Size</th>
                      </tr>
                    </thead>
                    <tbody>
                      {images.map((img) => (
                        <tr key={img.id} className="border-b border-border/50 hover:bg-muted/50">
                          <td className="px-4 py-2">
                            {img.tags.map((tag) => (
                              <div key={tag} className="font-mono text-xs text-foreground">{tag}</div>
                            ))}
                          </td>
                          <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{img.id}</td>
                          <td className="px-4 py-2 text-xs text-muted-foreground text-right">{img.size_mb} MB</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </div>

      {/* Deploy Progress */}
      {deployingDemo && (
        <DeployProgress
          demoId={deployingDemo.id}
          demoName={deployingDemo.name}
          apiBase={import.meta.env.VITE_API_URL || "http://localhost:9210"}
          onDone={handleDeployDone}
        />
      )}

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{deleteTarget?.name}"</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the demo configuration. Choose what else to clean up:
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-3 py-2">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={deleteOpts.destroyContainers}
                onChange={(e) => setDeleteOpts((o) => ({ ...o, destroyContainers: e.target.checked }))}
                className="rounded border-border"
              />
              <div>
                <div className="text-sm font-medium text-foreground">Destroy containers</div>
                <div className="text-xs text-muted-foreground">Stop and remove all running containers for this demo</div>
              </div>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={deleteOpts.removeImages}
                onChange={(e) => setDeleteOpts((o) => ({ ...o, removeImages: e.target.checked }))}
                className="rounded border-border"
              />
              <div>
                <div className="text-sm font-medium text-foreground">Remove images</div>
                <div className="text-xs text-muted-foreground">Delete pulled Docker images used by this demo's components</div>
              </div>
            </label>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete Demo
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
