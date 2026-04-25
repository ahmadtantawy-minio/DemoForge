import { useState, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { useDebugStore } from "../../stores/debugStore";
import { deployDemo, stopDemo, startDemo, destroyDemo, fetchDemos, updateDemo, saveDiagram, fetchInstances, fetchTaskStatus } from "../../api/client";
import { useDiagramStore } from "../../stores/diagramStore";
import { toast } from "../../lib/toast";
import DeployProgress from "../deploy/DeployProgress";
import DemoSelectorModal from "../shared/DemoSelectorModal";
import SettingsDialog from "../settings/SettingsDialog";
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
import { ArrowRightLeft, Sun, Moon, FileCode, Settings, SlidersHorizontal, Gauge, Terminal, BookOpen, BookmarkPlus, Save, RefreshCw, Eye, Bug, Clapperboard } from "lucide-react";
import { SaveAsTemplateDialog } from "../templates/SaveAsTemplateDialog";
import { Input } from "@/components/ui/input";
import GeneratedConfigViewer from "../shared/GeneratedConfigViewer";
import ConfigScriptPanel from "../config/ConfigScriptPanel";
import { copyDebugBundleToClipboard } from "../../lib/copyDebugBundle";
import DemoPresentationAuthoringDialog from "../demo-presentation/DemoPresentationAuthoringDialog";
import DemoPresentationPresenter from "../demo-presentation/DemoPresentationPresenter";
import type { DemoSlidePayload } from "../../api/client";

export default function Toolbar() {
  const { demos, activeDemoId, activeView, setDemos, setActiveView, updateDemoStatus, cockpitEnabled, toggleCockpit, walkthroughOpen, toggleWalkthrough, setInstances, setClusterHealth, showFaNotes, setShowFaNotes, faMode } = useDemoStore();
  const debugStore = useDebugStore();
  const [loading, setLoading] = useState<"deploy" | "stop" | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [deployTaskId, setDeployTaskId] = useState<string | undefined>(undefined);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [configViewerOpen, setConfigViewerOpen] = useState(false);
  const [scriptPanelOpen, setScriptPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [globalSettingsOpen, setGlobalSettingsOpen] = useState(false);
  const [resourceSettings, setResourceSettings] = useState({ default_memory: "", default_cpu: 0, max_memory: "", max_cpu: 0, total_memory: "", total_cpu: 0 });
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [copyingDebug, setCopyingDebug] = useState(false);

  const isDirty = useDiagramStore((s) => s.isDirty);
  const faId = useDemoStore((s) => s.faId);
  const [presentationOpen, setPresentationOpen] = useState(false);
  const [presenterOpen, setPresenterOpen] = useState(false);
  const [presenterSection, setPresenterSection] = useState<"intro" | "outro">("intro");
  const [presenterSlides, setPresenterSlides] = useState<DemoSlidePayload[]>([]);

  const handleForceSync = useCallback(async () => {
    if (!activeDemoId) return;
    setSyncing(true);
    try {
      const res = await fetchInstances(activeDemoId);
      setInstances(res.instances);
      if (res.cluster_health) setClusterHealth(res.cluster_health);
      const { updateNodeHealth } = useDiagramStore.getState();
      for (const inst of res.instances) updateNodeHealth(inst.node_id, inst.health);
      toast.success("State synced", { duration: 1500 });
    } catch {
      toast.error("Sync failed");
    } finally {
      setSyncing(false);
    }
  }, [activeDemoId, setInstances, setClusterHealth]);

  const handleCopyDebugBundle = useCallback(async () => {
    setCopyingDebug(true);
    try {
      const r = await copyDebugBundleToClipboard();
      if (r.ok) {
        toast.success(r.message, { description: "Paste into Slack, GitHub issue, or your notes on your dev PC." });
      } else {
        toast.error(r.message);
      }
    } finally {
      setCopyingDebug(false);
    }
  }, []);

  const handleSave = useCallback(() => {
    if (!activeDemoId) return;
    const { nodes, edges } = useDiagramStore.getState();
    const groups = nodes.filter((n) => n.type === "group");
    const componentNodes = nodes.filter((n) => n.type !== "group");
    saveDiagram(activeDemoId, [...componentNodes, ...groups], edges)
      .then(() => {
        useDiagramStore.getState().setDirty(false);
        toast.success("Diagram saved", { duration: 2000 });
      })
      .catch(() => {
        toast.error("Failed to save diagram");
      });
  }, [activeDemoId]);

  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const presentationReadOnly = activeDemo?.mode === "experience" && faMode !== "dev";

  const openPresenter = (section: "intro" | "outro", slides: DemoSlidePayload[]) => {
    if (!slides.length) return;
    setPresentationOpen(false);
    setPresenterSection(section);
    setPresenterSlides(slides);
    setPresenterOpen(true);
  };

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
    // Auto-save diagram before deploying so current UI state (ecParity, nodeCount, etc.) is always used
    const { nodes, edges } = useDiagramStore.getState();
    const groups = nodes.filter((n) => n.type === "group");
    const componentNodes = nodes.filter((n) => n.type !== "group");
    await saveDiagram(activeDemoId, [...componentNodes, ...groups], edges).catch(() => {});
    useDiagramStore.getState().setDirty(false);
    setShowFaNotes(false);
    updateDemoStatus(activeDemoId, "deploying");
    try {
      const res = await deployDemo(activeDemoId);
      setDeployTaskId(res.task_id);
      setDeploying(true);
      toast.info("Deployment starting...", { description: "Containers are being created. This may take a moment." });
    } catch (err: any) {
      updateDemoStatus(activeDemoId, "error");
      toast.error("Failed to start deployment", { description: err.message });
    }
  };

  const handleDeployDone = (success: boolean) => {
    setDeploying(false);
    setDeployTaskId(undefined);
    if (activeDemoId) {
      updateDemoStatus(activeDemoId, success ? "running" : "error");
    }
    if (success) {
      toast.success("Deployment completed", { description: "All containers are up and running." });
    } else {
      toast.error("Deployment failed", { description: "One or more containers failed to start." });
    }
    fetchDemos().then((res) => setDemos(res.demos)).catch(() => {});
  };

  // Poll a background task until it finishes, then call onDone.
  const pollTask = useCallback((demoId: string, taskId: string, onDone: (success: boolean, error?: string) => void) => {
    const interval = setInterval(async () => {
      try {
        const task = await fetchTaskStatus(demoId, taskId);
        if (task.finished || task.status === "done" || task.status === "error" || task.status === "timeout") {
          clearInterval(interval);
          onDone(task.status === "done", task.error || undefined);
        }
      } catch {
        // network blip — keep polling
      }
    }, 1000);
  }, []);

  const handleStop = async () => {
    if (!activeDemoId) return;
    setLoading("stop");
    updateDemoStatus(activeDemoId, "stopping");
    debugStore.addEntry("info", "Deploy", `Stopping demo ${activeDemoId}...`);
    try {
      const res = await stopDemo(activeDemoId);
      if (res.task_id) {
        pollTask(activeDemoId, res.task_id, (success, error) => {
          setLoading(null);
          if (success) {
            updateDemoStatus(activeDemoId, "stopped");
            debugStore.addEntry("info", "Deploy", "Demo stopped");
            toast.success("Demo stopped");
          } else {
            updateDemoStatus(activeDemoId, "running");
            debugStore.addEntry("error", "Deploy", "Stop failed", error);
            toast.error("Failed to stop demo", { description: error });
          }
          fetchDemos().then((r) => setDemos(r.demos)).catch(() => {});
        });
      } else {
        updateDemoStatus(activeDemoId, "stopped");
        toast.success("Demo stopped");
        setLoading(null);
      }
    } catch (err: any) {
      updateDemoStatus(activeDemoId, "running");
      debugStore.addEntry("error", "Deploy", "Stop failed", err.message);
      toast.error("Failed to stop demo", { description: err.message });
      setLoading(null);
    }
  };

  const handleStart = async () => {
    if (!activeDemoId) return;
    // Auto-save so any edits made in stopped state are persisted before resuming
    const { nodes, edges } = useDiagramStore.getState();
    const groups = nodes.filter((n) => n.type === "group");
    const componentNodes = nodes.filter((n) => n.type !== "group");
    await saveDiagram(activeDemoId, [...componentNodes, ...groups], edges).catch(() => {});
    useDiagramStore.getState().setDirty(false);
    setLoading("deploy");
    updateDemoStatus(activeDemoId, "deploying");
    try {
      const res = await startDemo(activeDemoId);
      if (res.task_id) {
        pollTask(activeDemoId, res.task_id, (success, error) => {
          setLoading(null);
          if (success) {
            updateDemoStatus(activeDemoId, "running");
            toast.success("Demo started");
          } else {
            updateDemoStatus(activeDemoId, "stopped");
            toast.error("Failed to start demo", { description: error });
          }
          fetchDemos().then((r) => setDemos(r.demos)).catch(() => {});
        });
      } else {
        updateDemoStatus(activeDemoId, "running");
        toast.success("Demo started");
        setLoading(null);
      }
    } catch (err: any) {
      updateDemoStatus(activeDemoId, "stopped");
      toast.error("Failed to start demo", { description: err.message });
      setLoading(null);
    }
  };

  const handleDestroy = async () => {
    if (!activeDemoId) return;
    setLoading("stop");
    updateDemoStatus(activeDemoId, "stopping");
    try {
      const res = await destroyDemo(activeDemoId);
      if (res.task_id) {
        pollTask(activeDemoId, res.task_id, (success, error) => {
          setLoading(null);
          if (success) {
            updateDemoStatus(activeDemoId, "not_deployed");
            toast.success("Demo destroyed");
          } else {
            updateDemoStatus(activeDemoId, "error");
            toast.error("Failed to destroy demo", { description: error });
          }
          fetchDemos().then((r) => setDemos(r.demos)).catch(() => {});
        });
      } else {
        updateDemoStatus(activeDemoId, "not_deployed");
        toast.success("Demo destroyed");
        setLoading(null);
        fetchDemos().then((r) => setDemos(r.demos)).catch(() => {});
      }
    } catch (err: any) {
      toast.error("Failed to destroy demo", { description: err.message });
      setLoading(null);
    }
  };

  const isTransitioning = activeDemo?.status === "deploying" || activeDemo?.status === "stopping";

  // Tooltip text for disabled deploy/stop buttons
  const deployTooltip = !activeDemoId
    ? "Select a demo first"
    : activeDemo?.status === "running"
    ? "Demo is already running"
    : activeDemo?.status === "deploying"
    ? "Deployment in progress"
    : activeDemo?.status === "stopping"
    ? "Demo is stopping"
    : null;

  const stopTooltip = !activeDemoId
    ? "Select a demo first"
    : activeDemo?.status === "stopped"
    ? "Demo is already stopped"
    : activeDemo?.status === "deploying"
    ? "Deployment in progress"
    : activeDemo?.status === "stopping"
    ? "Already stopping"
    : !activeDemo?.status || activeDemo?.status === "error" || activeDemo?.status === "not_deployed"
    ? "Demo is not running"
    : null;

  const deployDisabled = !activeDemoId || loading !== null || activeDemo?.status === "running" || activeDemo?.status === "deploying" || activeDemo?.status === "stopping";
  const stopDisabled = !activeDemoId || loading !== null || activeDemo?.status === "stopped" || activeDemo?.status === "stopping" || !activeDemo?.status || activeDemo?.status === "error" || activeDemo?.status === "not_deployed";

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
          {faId && (
            <span className="text-[11px] text-muted-foreground/60 truncate max-w-[200px]" title={faId}>
              {faId}
            </span>
          )}
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
            <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${
              activeDemo.status === "running"
                ? "bg-green-500/15 text-green-400"
                : activeDemo.status === "deploying"
                ? "bg-yellow-500/15 text-yellow-400"
                : activeDemo.status === "stopping"
                ? "bg-orange-500/15 text-orange-400"
                : activeDemo.status === "error"
                ? "bg-red-500/15 text-red-400"
                : "bg-muted text-muted-foreground"
            }`}>
              {isTransitioning ? (
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
              ) : (
                <span className={`w-1.5 h-1.5 rounded-full ${
                  activeDemo.status === "running" ? "bg-green-400"
                  : activeDemo.status === "error" ? "bg-red-400"
                  : "bg-muted-foreground"
                }`} />
              )}
              {activeDemo.status === "stopping" ? "stopping…" : activeDemo.status === "not_deployed" ? "not deployed" : activeDemo.status}
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

        {/* Save - shown in design time and stopped state; hidden while running or transitioning */}
        {activeDemoId && activeDemo?.status !== "running" && activeDemo?.status !== "deploying" && activeDemo?.status !== "stopping" && (
          <button
            onClick={handleSave}
            disabled={!isDirty}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              isDirty
                ? "bg-blue-600 text-white hover:bg-blue-500"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            }`}
            title={isDirty ? "Save changes (Cmd+S)" : "No unsaved changes"}
          >
            <Save size={14} />
            Save
          </button>
        )}

        {/* Deploy/Stop/Start/Destroy — state-driven, only when demo selected */}
        {activeDemoId && (
          <>
            {/* Deploy — shown when not running, not stopped, not transitioning */}
            {activeDemo?.status !== "running" && activeDemo?.status !== "stopped" && activeDemo?.status !== "stopping" && activeDemo?.status !== "deploying" && (
              <Button
                onClick={handleDeploy}
                disabled={deployDisabled}
                size="sm"
                className="h-7 text-xs px-3 bg-green-600 hover:bg-green-500 text-white"
              >
                Deploy
              </Button>
            )}

            {/* Start — shown when stopped */}
            {activeDemo?.status === "stopped" && (
              <Button
                onClick={handleStart}
                disabled={loading !== null}
                size="sm"
                className="h-7 text-xs px-3 bg-green-600 hover:bg-green-500 text-white"
              >
                {loading === "deploy" ? "Starting..." : "▶ Start"}
              </Button>
            )}

            {/* Stop — shown when running */}
            {activeDemo?.status === "running" && (
              <Button
                onClick={handleStop}
                disabled={loading !== null}
                size="sm"
                className="h-7 text-xs px-3 bg-amber-600 hover:bg-amber-500 text-white"
              >
                {loading === "stop" ? "Stopping..." : "⏸ Stop"}
              </Button>
            )}

            {/* Destroy — shown when running or stopped */}
            {(activeDemo?.status === "running" || activeDemo?.status === "stopped") && (
              <Button
                onClick={handleDestroy}
                disabled={loading !== null}
                variant="destructive"
                size="sm"
                className="h-7 text-xs px-3"
              >
                {loading === "stop" && activeDemo?.status !== "running" ? "Destroying..." : "Destroy"}
              </Button>
            )}

            {/* Deploying/Stopping transitions — disabled indicator */}
            {(activeDemo?.status === "deploying" || activeDemo?.status === "stopping") && (
              <Button disabled size="sm" className="h-7 text-xs px-3 bg-yellow-600 text-white">
                {activeDemo.status === "deploying" ? "Deploying..." : "Stopping..."}
              </Button>
            )}

            {/* Sync — when running, deploying, stopping, or destroying */}
            {(activeDemo?.status === "running" || activeDemo?.status === "deploying" || activeDemo?.status === "stopping") && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    onClick={handleForceSync}
                    disabled={syncing}
                    size="sm"
                    variant="outline"
                    className="h-7 w-7 p-0"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent><p className="text-xs">Force sync state</p></TooltipContent>
              </Tooltip>
            )}

            {/* Save as Template — design time only (not during transitions) */}
            {activeDemo?.status !== "running" && activeDemo?.status !== "stopped" && activeDemo?.status !== "deploying" && activeDemo?.status !== "stopping" && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    onClick={() => setSaveTemplateOpen(true)}
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs px-2 gap-1"
                  >
                    <BookmarkPlus className="w-3.5 h-3.5" />
                    Save as Template
                  </Button>
                </TooltipTrigger>
                <TooltipContent><p className="text-xs">Save current demo as a reusable template</p></TooltipContent>
              </Tooltip>
            )}
          </>
        )}

        {activeDemoId && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={handleCopyDebugBundle}
                  disabled={copyingDebug}
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                  data-testid="toolbar-copy-debug"
                >
                  <Bug className={`w-3.5 h-3.5 ${copyingDebug ? "animate-pulse" : ""}`} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-xs font-medium">Copy debug bundle</p>
                <p className="text-[11px] text-muted-foreground mt-1 max-w-[220px]">
                  Clipboard: URL, logs, /api/health/system, response probe for this page. Shortcut: ⌃⇧D / ⇧⌘D
                </p>
              </TooltipContent>
            </Tooltip>
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
                  onClick={() => setScriptPanelOpen(true)}
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                >
                  <Terminal className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Setup Script</p></TooltipContent>
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
                  <SlidersHorizontal className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Demo Settings</p></TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={(e) => { e.stopPropagation(); setShowFaNotes(!showFaNotes); }}
                  variant="ghost"
                  size="sm"
                  className={`h-7 px-2 flex items-center gap-1 text-xs ${showFaNotes ? "text-amber-400 bg-amber-400/10" : "text-muted-foreground hover:text-foreground"}`}
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span>FA notes</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Toggle FA internal notes</p></TooltipContent>
            </Tooltip>
            <Button
              onClick={(e) => { e.stopPropagation(); toggleCockpit(); }}
              variant="ghost"
              size="sm"
              className={`h-7 w-7 p-0 ${cockpitEnabled ? "text-green-400 bg-green-400/10" : "text-muted-foreground hover:text-foreground"}`}
              title={cockpitEnabled ? "Cockpit On" : "Cockpit Off"}
            >
              <Gauge className="w-3.5 h-3.5" />
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={(e) => { e.stopPropagation(); toggleWalkthrough(); }}
                  variant="ghost"
                  size="sm"
                  className={`h-7 w-7 p-0 ${walkthroughOpen ? "text-blue-400 bg-blue-400/10" : "text-muted-foreground hover:text-foreground"}`}
                >
                  <BookOpen className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent><p className="text-xs">Walkthrough</p></TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={(e) => {
                    e.stopPropagation();
                    setPresentationOpen(true);
                  }}
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                  data-testid="toolbar-slides"
                >
                  <Clapperboard className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-xs font-medium">Intro / outro slides</p>
                <p className="text-[11px] text-muted-foreground mt-1 max-w-[200px]">
                  Per-demo title cards before and after the live demo (saved in demo YAML).
                </p>
              </TooltipContent>
            </Tooltip>
          </>
        )}

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

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              onClick={() => setGlobalSettingsOpen(true)}
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
            >
              <Settings className="w-3.5 h-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent><p className="text-xs">Settings</p></TooltipContent>
        </Tooltip>

        <Button
          onClick={() => debugStore.toggle()}
          variant="ghost"
          size="sm"
          className={`h-7 text-xs px-2 ${debugStore.isOpen ? "text-primary" : "text-muted-foreground"}`}
        >
          {debugStore.entries.filter((e) => e.level === "error").length > 0
            ? `Logs (${debugStore.entries.filter((e) => e.level === "error").length})`
            : "Logs"}
        </Button>

        {deploying && activeDemoId && activeDemo && (
          <DeployProgress
            demoId={activeDemoId}
            demoName={activeDemo.name}
            onDone={handleDeployDone}
            taskId={deployTaskId}
          />
        )}
      </div>

      <DemoSelectorModal open={selectorOpen} onOpenChange={setSelectorOpen} />
      <SettingsDialog open={globalSettingsOpen} onOpenChange={setGlobalSettingsOpen} />

      {activeDemoId && (
        <GeneratedConfigViewer
          open={configViewerOpen}
          onOpenChange={setConfigViewerOpen}
          demoId={activeDemoId}
        />
      )}

      {activeDemoId && (
        <ConfigScriptPanel
          open={scriptPanelOpen}
          onOpenChange={setScriptPanelOpen}
          demoId={activeDemoId}
        />
      )}

      {activeDemoId && (
        <SaveAsTemplateDialog
          open={saveTemplateOpen}
          onOpenChange={setSaveTemplateOpen}
          demoId={activeDemoId}
          demoName={activeDemo?.name}
          demoDescription={activeDemo?.description}
          sourceTemplateId={activeDemo?.source_template_id}
          onSaved={() => {
            toast.success("Template saved");
            setSaveTemplateOpen(false);
          }}
        />
      )}

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

      {activeDemoId && (
        <>
          <DemoPresentationAuthoringDialog
            open={presentationOpen}
            onOpenChange={setPresentationOpen}
            demoId={activeDemoId}
            readOnly={presentationReadOnly}
            onPresent={openPresenter}
          />
          <DemoPresentationPresenter
            open={presenterOpen}
            section={presenterSection}
            slides={presenterSlides}
            onClose={() => setPresenterOpen(false)}
          />
        </>
      )}
    </TooltipProvider>
  );
}
