import { useState } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { useDebugStore } from "../../stores/debugStore";
import { deployDemo, stopDemo, fetchDemos, updateDemo } from "../../api/client";
import { toast } from "sonner";
import DeployProgress from "../deploy/DeployProgress";
import DemoSelectorModal from "../shared/DemoSelectorModal";
import LicenseSettings from "../admin/LicenseSettings";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ArrowRightLeft, Sun, Moon, Key, FileCode, Settings, Gauge } from "lucide-react";
import { Input } from "@/components/ui/input";
import GeneratedConfigViewer from "../shared/GeneratedConfigViewer";

interface ToolbarProps {
  cockpitEnabled?: boolean;
  onToggleCockpit?: () => void;
}

export default function Toolbar({ cockpitEnabled, onToggleCockpit }: ToolbarProps = {}) {
  const { demos, activeDemoId, activeView, setDemos, setActiveView, updateDemoStatus } = useDemoStore();
  const debugStore = useDebugStore();
  const [loading, setLoading] = useState<"deploy" | "stop" | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [licensesOpen, setLicensesOpen] = useState(false);
  const [configViewerOpen, setConfigViewerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [resourceSettings, setResourceSettings] = useState({ default_memory: "", default_cpu: 0, max_memory: "", max_cpu: 0, total_memory: "", total_cpu: 0 });
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");

  const activeDemo = demos.find((d) => d.id === activeDemoId);

  const handleRename = async () => {
    if (!activeDemoId || !renameName.trim()) { setRenaming(false); return; }
    try {
      await updateDemo(activeDemoId, { name: renameName.trim() });
      const res = await fetchDemos();
      setDemos(res.demos);
      toast.success("Demo renamed");
    } catch (err: any) {
      toast.error("Rename failed", { description: err.message });
    }
    setRenaming(false);
  };

  const handleDeploy = async () => {
    if (!activeDemoId) return;
    updateDemoStatus(activeDemoId, "deploying");
    setDeploying(true);
    toast.info("Deployment started");
    deployDemo(activeDemoId).catch(() => {});
  };

  const handleDeployDone = (success: boolean) => {
    setDeploying(false);
    if (activeDemoId) {
      updateDemoStatus(activeDemoId, success ? "running" : "error");
    }
    if (success) {
      toast.success("Deployment successful");
    } else {
      toast.error("Deployment failed");
    }
    fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
  };

  const handleStop = async () => {
    if (!activeDemoId) return;
    setLoading("stop");
    debugStore.addEntry("info", "Deploy", `Stopping demo ${activeDemoId}...`);
    try {
      await stopDemo(activeDemoId);
      updateDemoStatus(activeDemoId, "stopped");
      debugStore.addEntry("info", "Deploy", `Demo stopped`);
      toast.success("Demo stopped");
    } catch (err: any) {
      debugStore.addEntry("error", "Deploy", `Stop failed`, err.message);
      toast.error("Failed to stop demo", { description: err.message });
    } finally {
      setLoading(null);
    }
  };

  const statusColor: Record<string, string> = {
    running: "text-green-400",
    deploying: "text-yellow-400",
    error: "text-red-400",
    stopped: "text-muted-foreground",
  };

  // Tooltip text for disabled deploy/stop buttons
  const deployTooltip = !activeDemoId
    ? "Select a demo first"
    : activeDemo?.status === "running"
    ? "Demo is already running"
    : activeDemo?.status === "deploying"
    ? "Deployment in progress"
    : null;

  const stopTooltip = !activeDemoId
    ? "Select a demo first"
    : activeDemo?.status === "stopped"
    ? "Demo is already stopped"
    : activeDemo?.status === "deploying"
    ? "Deployment in progress"
    : !activeDemo?.status || activeDemo?.status === "error"
    ? "Demo is not running"
    : null;

  const deployDisabled = !activeDemoId || loading !== null || activeDemo?.status === "running" || activeDemo?.status === "deploying";
  const stopDisabled = !activeDemoId || loading !== null || activeDemo?.status === "stopped" || !activeDemo?.status || activeDemo?.status === "error";

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex items-center gap-3 px-4 py-2 bg-card border-b border-border text-foreground text-sm">
        <div className="flex items-center gap-2 mr-2">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="6" y="18" width="14" height="10" rx="2" fill="#C72C48" opacity="0.4"/>
            <rect x="10" y="11" width="14" height="10" rx="2" fill="#C72C48" opacity="0.7"/>
            <rect x="14" y="4" width="14" height="10" rx="2" fill="#C72C48"/>
          </svg>
          <span className="font-bold text-foreground">DemoForge</span>
        </div>

        {/* Demo selector trigger */}
        {activeDemo ? (
          <div className="flex items-center gap-2">
            {renaming ? (
              <input
                autoFocus
                value={renameName}
                onChange={(e) => setRenameName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleRename(); if (e.key === "Escape") setRenaming(false); }}
                onBlur={handleRename}
                className="text-sm font-medium text-foreground bg-transparent border-b border-primary outline-none w-32 px-0"
              />
            ) : (
              <span
                className="text-sm font-medium text-foreground cursor-pointer hover:underline"
                onDoubleClick={() => { setRenaming(true); setRenameName(activeDemo.name); }}
                title="Double-click to rename"
              >
                {activeDemo.name}
              </span>
            )}
            <span className={`text-xs ${statusColor[activeDemo.status] ?? "text-muted-foreground"}`}>
              {activeDemo.status}
            </span>
            <Button
              variant="secondary"
              size="sm"
              className="h-6 text-[11px] px-2 gap-1"
              onClick={() => setSelectorOpen(true)}
            >
              <ArrowRightLeft className="w-3 h-3" />
              Switch
            </Button>
          </div>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            className="h-7 text-xs px-3"
            onClick={() => setSelectorOpen(true)}
          >
            Select Demo
          </Button>
        )}

        <div className="flex-1" />

        {/* View switcher - only when demo selected */}
        {activeDemoId && (
          <div className="flex items-center gap-1 bg-muted rounded p-0.5">
            {(["diagram", "control-plane"] as const).map((view) => (
              <Button
                key={view}
                variant={activeView === view ? "secondary" : "ghost"}
                size="sm"
                className={`h-7 px-3 text-xs ${activeView === view ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setActiveView(view)}
              >
                {view === "diagram" ? "Diagram" : "Instances"}
              </Button>
            ))}
          </div>
        )}

        {/* Deploy/Stop - only when demo selected */}
        {activeDemoId && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button
                    onClick={handleDeploy}
                    disabled={deployDisabled}
                    size="sm"
                    className="h-7 text-xs px-3 bg-green-600 hover:bg-green-500 text-white"
                  >
                    {loading === "deploy" ? "Deploying..." : activeDemo?.status === "deploying" ? "Deploying..." : "Deploy"}
                  </Button>
                </span>
              </TooltipTrigger>
              {deployTooltip && (
                <TooltipContent>
                  <p className="text-xs">{deployTooltip}</p>
                </TooltipContent>
              )}
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button
                    onClick={handleStop}
                    disabled={stopDisabled}
                    variant="destructive"
                    size="sm"
                    className="h-7 text-xs px-3"
                  >
                    {loading === "stop" ? "Stopping..." : "Stop"}
                  </Button>
                </span>
              </TooltipTrigger>
              {stopTooltip && (
                <TooltipContent>
                  <p className="text-xs">{stopTooltip}</p>
                </TooltipContent>
              )}
            </Tooltip>
          </>
        )}

        {activeDemoId && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={() => setConfigViewerOpen(true)}
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                >
                  <FileCode className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Generated Config</p></TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={() => {
                    // Load current resource settings from demo
                    import("../../api/client").then(({ fetchDemo }) =>
                      fetchDemo(activeDemoId!).then((demo: any) => {
                        const r = demo.resources || {};
                        setResourceSettings({
                          default_memory: r.default_memory || "",
                          default_cpu: r.default_cpu || 0,
                          max_memory: r.max_memory || "",
                          max_cpu: r.max_cpu || 0,
                          total_memory: r.total_memory || "",
                          total_cpu: r.total_cpu || 0,
                        });
                        setSettingsOpen(true);
                      })
                    );
                  }}
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                >
                  <Settings className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Demo Settings</p></TooltipContent>
            </Tooltip>
            <Button
              onClick={(e) => { e.stopPropagation(); onToggleCockpit?.(); }}
              variant="ghost"
              size="sm"
              className={`h-7 w-7 p-0 ${cockpitEnabled ? "text-green-400 bg-green-400/10" : "text-muted-foreground hover:text-foreground"}`}
              title={cockpitEnabled ? "Cockpit On" : "Cockpit Off"}
            >
              <Gauge className="w-3.5 h-3.5" />
            </Button>
          </>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              onClick={() => setLicensesOpen(true)}
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
            >
              <Key className="w-3.5 h-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent><p className="text-xs">Licenses</p></TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              onClick={() => {
                const html = document.documentElement;
                const isDark = html.classList.contains("dark");
                html.classList.toggle("dark", !isDark);
                localStorage.setItem("demoforge-theme", isDark ? "light" : "dark");
              }}
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
            >
              <Sun className="w-3.5 h-3.5 hidden dark:block" />
              <Moon className="w-3.5 h-3.5 block dark:hidden" />
            </Button>
          </TooltipTrigger>
          <TooltipContent><p className="text-xs">Toggle theme</p></TooltipContent>
        </Tooltip>

        <Button
          onClick={() => debugStore.toggle()}
          variant="ghost"
          size="sm"
          className={`h-7 text-xs px-2 ${debugStore.isOpen ? "text-primary" : "text-muted-foreground"}`}
        >
          {debugStore.entries.filter((e) => e.level === "error").length > 0
            ? `Debug (${debugStore.entries.filter((e) => e.level === "error").length})`
            : "Debug"}
        </Button>

        {deploying && activeDemoId && activeDemo && (
          <DeployProgress
            demoId={activeDemoId}
            demoName={activeDemo.name}
            apiBase={import.meta.env.VITE_API_URL || "http://localhost:8000"}
            onDone={handleDeployDone}
          />
        )}
      </div>

      <DemoSelectorModal open={selectorOpen} onOpenChange={setSelectorOpen} />

      {activeDemoId && (
        <GeneratedConfigViewer
          open={configViewerOpen}
          onOpenChange={setConfigViewerOpen}
          demoId={activeDemoId}
        />
      )}

      <Dialog open={licensesOpen} onOpenChange={setLicensesOpen}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-base">Licenses</DialogTitle>
          </DialogHeader>
          <LicenseSettings />
        </DialogContent>
      </Dialog>

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base">Demo Resource Settings</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <p className="text-xs text-muted-foreground">
              Set default resource limits for all containers in this demo. Leave empty to use each component's manifest defaults.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Default Memory</label>
                <Input
                  value={resourceSettings.default_memory}
                  onChange={(e) => setResourceSettings({ ...resourceSettings, default_memory: e.target.value })}
                  placeholder="e.g. 512m, 1g"
                  className="h-8 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Default CPU</label>
                <Input
                  type="number"
                  step="0.25"
                  min="0"
                  value={resourceSettings.default_cpu || ""}
                  onChange={(e) => setResourceSettings({ ...resourceSettings, default_cpu: parseFloat(e.target.value) || 0 })}
                  placeholder="e.g. 0.5, 1.0"
                  className="h-8 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Max Memory (cap)</label>
                <Input
                  value={resourceSettings.max_memory}
                  onChange={(e) => setResourceSettings({ ...resourceSettings, max_memory: e.target.value })}
                  placeholder="e.g. 2g"
                  className="h-8 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Max CPU (cap)</label>
                <Input
                  type="number"
                  step="0.25"
                  min="0"
                  value={resourceSettings.max_cpu || ""}
                  onChange={(e) => setResourceSettings({ ...resourceSettings, max_cpu: parseFloat(e.target.value) || 0 })}
                  placeholder="e.g. 2.0"
                  className="h-8 text-sm"
                />
              </div>
            </div>
            <div className="border-t border-border pt-3 mt-1">
              <p className="text-xs text-muted-foreground mb-2">
                Total demo budget — if set, per-container resources are scaled down proportionally to fit within this cap.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Total Memory Budget</label>
                  <Input
                    value={resourceSettings.total_memory}
                    onChange={(e) => setResourceSettings({ ...resourceSettings, total_memory: e.target.value })}
                    placeholder="e.g. 32g"
                    className="h-8 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Total CPU Budget</label>
                  <Input
                    type="number"
                    step="1"
                    min="0"
                    value={resourceSettings.total_cpu || ""}
                    onChange={(e) => setResourceSettings({ ...resourceSettings, total_cpu: parseFloat(e.target.value) || 0 })}
                    placeholder="e.g. 16"
                    className="h-8 text-sm"
                  />
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" size="sm" onClick={() => setSettingsOpen(false)}>Cancel</Button>
              <Button
                size="sm"
                onClick={() => {
                  if (!activeDemoId) return;
                  updateDemo(activeDemoId, { resources: resourceSettings } as any)
                    .then(() => { toast.success("Resource settings saved"); setSettingsOpen(false); })
                    .catch((e: any) => toast.error("Failed to save", { description: e.message }));
                }}
              >
                Save
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}
