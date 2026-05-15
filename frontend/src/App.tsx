import { useCallback, useEffect, useRef, useState } from "react";
import { useDemoStore } from "./stores/demoStore";
import { useDiagramStore } from "./stores/diagramStore";
import { useDebugStore } from "./stores/debugStore";
import { DEBUG_LOG_TTL_MS } from "./lib/debugLogTtl";
import { buildStructuredIntegrationDetails } from "./lib/integrationLogDisplay";
import { fetchDemos, fetchInstances, getFailoverStatus, getResilienceStatus, fetchIdentity } from "./api/client";
import { Toaster, toast } from "sonner";
import Toolbar from "./components/toolbar/Toolbar";
import ComponentPalette from "./components/palette/ComponentPalette";
import DiagramCanvas from "./components/canvas/DiagramCanvas";
import PropertiesPanel from "./components/properties/PropertiesPanel";
import ControlPlane from "./components/control-plane/ControlPlane";
import DemoManager from "./components/admin/DemoManager";
import TerminalPanel from "./components/terminal/TerminalPanel";
import DebugPanel from "./components/debug/DebugPanel";
import WelcomeScreen from "./components/shared/WelcomeScreen";
import CockpitOverlay from "./components/cockpit/CockpitOverlay";
import DesignerWebUIOverlay from "./components/canvas/DesignerWebUIOverlay";
import WalkthroughPanel from "./components/walkthrough/WalkthroughPanel";
import { getWalkthrough, WalkthroughStep } from "./api/client";
import AppNav from "./components/nav/AppNav";
import DeployStatusBar from "./components/deploy/DeployStatusBar";
import { HomePage } from "./pages/HomePage";
import { TemplatesPage } from "./pages/TemplatesPage";
import { ImagesPage } from "./pages/ImagesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ReadinessPage } from "./pages/ReadinessPage";
import { FAManagementPage } from "./pages/FAManagementPage";
import { ConnectivityPage } from "./pages/ConnectivityPage";
import { copyDebugBundleToClipboard } from "./lib/copyDebugBundle";

export default function App() {
  const { setDemos, setInstances, setClusterHealth, activeDemoId, demos, activeView, cockpitEnabled, walkthroughOpen, setWalkthroughOpen, setResilienceProbes, currentPage, faMode, layoutFocusMode, setLayoutFocusMode, laserPointerMode } = useDemoStore();
  const debugOpen = useDebugStore((s) => s.isOpen);
  const addDebugEntry = useDebugStore((s) => s.addEntry);
  const prevClusterHealth = useRef<Record<string, string>>({});
  const prevInstances = useRef<Record<string, { health: string; init_status: string }>>({});
  const prevDemoStatuses = useRef<Record<string, string>>({});
  const provisionEmitted = useRef<Set<string>>(new Set());
  const initResultsEmitted = useRef<Set<string>>(new Set());
  /** Per-demo map of integration event id → last-seen ts_ms (pruned for TTL). */
  const integrationEventSeen = useRef<Map<string, Map<string, number>>>(new Map());
  const [terminalTabs, setTerminalTabs] = useState<{ nodeId: string }[]>([]);
  const [walkthroughSteps, setWalkthroughSteps] = useState<WalkthroughStep[]>([]);
  const [terminalHeight, setTerminalHeight] = useState(200);
  const [bottomTab, setBottomTab] = useState<"terminal" | "logs">("terminal");
  const [leftPanelWidth, setLeftPanelWidth] = useState(192);
  const [rightPanelWidth, setRightPanelWidth] = useState(288);
  const isDragging = useRef(false);
  const panelSnapshotRef = useRef<{ left: number; right: number; bottom: number } | null>(null);

  useEffect(() => {
    if (currentPage !== "designer" && layoutFocusMode) {
      setLayoutFocusMode(false);
    }
  }, [currentPage, layoutFocusMode, setLayoutFocusMode]);

  useEffect(() => {
    setLayoutFocusMode(false);
  }, [activeDemoId, setLayoutFocusMode]);

  useEffect(() => {
    if (layoutFocusMode) {
      if (!panelSnapshotRef.current) {
        panelSnapshotRef.current = {
          left: leftPanelWidth,
          right: rightPanelWidth,
          bottom: terminalHeight,
        };
      }
      setLeftPanelWidth(0);
      setRightPanelWidth(0);
      setTerminalHeight(0);
    } else {
      const snap = panelSnapshotRef.current;
      if (snap) {
        setLeftPanelWidth(snap.left);
        setRightPanelWidth(snap.right);
        setTerminalHeight(snap.bottom);
        panelSnapshotRef.current = null;
      }
    }
  }, [layoutFocusMode]);

  // Subscribe to diagram edges — emit Provision entries once edges are loaded for an active demo
  const edges = useDiagramStore((s) => s.edges);
  const nodes = useDiagramStore((s) => s.nodes);
  const designerWebUiOverlay = useDiagramStore((s) => s.designerWebUiOverlay);
  const setDesignerWebUiOverlay = useDiagramStore((s) => s.setDesignerWebUiOverlay);
  useEffect(() => {
    if (!activeDemoId) return;
    if (provisionEmitted.current.has(activeDemoId)) return;
    const activeDemo = useDemoStore.getState().demos.find((d) => d.id === activeDemoId);
    if (!activeDemo || !["running", "deploying"].includes(activeDemo.status)) return;
    const INTEGRATION_TYPES: Record<string, string> = {
      "dashboard-provision": "requesting dashboard provisioning",
      "data-provision": "requesting data provisioning",
      "schema-provision": "requesting schema provisioning",
    };
    const integrationEdges = edges.filter((e) => INTEGRATION_TYPES[(e.data as any)?.connectionType]);
    if (integrationEdges.length === 0) return;
    provisionEmitted.current.add(activeDemoId);
    for (const edge of integrationEdges) {
      const edgeData = edge.data as any;
      const srcNode = nodes.find((n) => n.id === edge.source);
      const tgtNode = nodes.find((n) => n.id === edge.target);
      const srcLabel = (srcNode?.data as any)?.displayName || (srcNode?.data as any)?.label || edge.source;
      const tgtLabel = (tgtNode?.data as any)?.displayName || (tgtNode?.data as any)?.label || edge.target;
      addDebugEntry("info", "Provision", `${srcLabel} → ${tgtLabel}: ${INTEGRATION_TYPES[edgeData.connectionType]}`, `Edge type: ${edgeData.connectionType}`);
    }
  }, [activeDemoId, edges]);

  // Fetch FA identity on mount
  useEffect(() => {
    fetchIdentity()
      .then(({ fa_id, identified, mode, hub_local }) => useDemoStore.getState().setFaIdentity(fa_id, identified, mode, hub_local))
      .catch(() => {});
  }, []);

  // Global shortcut: copy debug bundle (clipboard) — avoid when typing in inputs
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || !e.shiftKey) return;
      if (e.key !== "D" && e.key !== "d") return;
      const t = e.target as HTMLElement | null;
      if (t?.closest("input,textarea,select,[contenteditable=true]")) return;
      e.preventDefault();
      copyDebugBundleToClipboard().then((r) => {
        addDebugEntry(r.ok ? "info" : "error", "DebugBundle", r.message);
        if (r.ok) {
          toast.success(r.message, { description: "Paste on your dev PC (issue chat, notes, etc.)." });
        } else {
          toast.error(r.message);
        }
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [addDebugEntry]);

  // Initial load + periodic sync of demo status from backend.
  // Preserve transitional states (deploying/stopping) so the background poll
  // doesn't overwrite local state while a task is actively in progress.
  useEffect(() => {
    const sync = () => fetchDemos().then((res) => {
      const current = useDemoStore.getState().demos;
      const merged = res.demos.map((d: any) => {
        const local = current.find((c) => c.id === d.id);
        // Preserve local transitional state only while the backend agrees it's still transitioning.
        // Once the backend reports a stable state (running, stopped, error), let it through.
        if (local && (local.status === "deploying" || local.status === "stopping")
            && (d.status === "deploying" || d.status === "stopping")) {
          return { ...d, status: local.status };
        }
        return d;
      });
      setDemos(merged);
      // Track demo status transitions for lifecycle log
      for (const d of merged) {
        const prev = prevDemoStatuses.current[d.id];
        if (prev !== undefined && prev !== d.status) {
          const level = d.status === "error" ? "error" : "info";
          addDebugEntry(level, "Lifecycle", `Demo "${d.id}": ${prev} → ${d.status}`);
          // Reset emit guards on new deploy so they re-fire for the fresh run
          if (d.status === "deploying") {
            provisionEmitted.current.delete(d.id);
            initResultsEmitted.current.delete(d.id);
            integrationEventSeen.current.delete(d.id);
          }
        }
        prevDemoStatuses.current[d.id] = d.status;
      }
    }).catch(() => {});
    sync();
    const interval = setInterval(sync, 5000);
    return () => clearInterval(interval);
  }, [setDemos]);

  // Poll instances when active demo is running or deploying
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  useEffect(() => {
    if (!activeDemoId || !["running", "deploying"].includes(activeDemo?.status || "")) {
      setInstances([]);
      return;
    }
    const syncInstances = () =>
      fetchInstances(activeDemoId).then((res) => {
        setInstances(res.instances);
        if (res.cluster_health) {
          setClusterHealth(res.cluster_health);
          // Log cluster health changes with context
          for (const [id, status] of Object.entries(res.cluster_health)) {
            const prev = prevClusterHealth.current[id];
            if (prev !== undefined && prev !== status) {
              const level = status === "healthy" ? "info" : "warn";
              const clusterNodes = res.instances.filter((i) => i.node_id.startsWith(`${id}-node-`));
              const healthyNodes = clusterNodes.filter((i) => i.health === "healthy").length;
              const statusMeaning: Record<string, string> = {
                healthy: "mc admin info: all erasure stripes meet write quorum.",
                degraded: "mc admin info: reduced redundancy; write quorum still met on all stripes.",
                quorum_lost: "mc admin info: at least one erasure stripe below write quorum.",
                unreachable: "mc admin info unavailable; L3 /minio/health/cluster check failed.",
              };
              const details = [
                `Transition: ${prev} → ${status}`,
                `Cluster: ${id} (demo: ${activeDemoId})`,
                `Nodes up: ${healthyNodes}/${clusterNodes.length}`,
                `Checked via: mc admin info --json (per-stripe quorum); L3 HTTP fallback`,
                `Meaning: ${statusMeaning[status] ?? status}`,
              ].join("\n");
              addDebugEntry(level, "ClusterHealth", `${id}: ${prev} → ${status}`, details);
            }
          }
          prevClusterHealth.current = res.cluster_health;
        }
        // Track container lifecycle transitions
        const currentIds = new Set(res.instances.map((i: any) => i.node_id));
        for (const inst of res.instances) {
          const prev = prevInstances.current[inst.node_id];
          const h = inst.health ?? "";
          const init = inst.init_status ?? "";
          if (prev) {
            if (prev.health !== h && h) {
              const level = h === "error" ? "error" : h === "healthy" ? "info" : "warn";
              addDebugEntry(level, "Lifecycle", `${inst.node_id}: ${prev.health || "?"} → ${h}`, `Container: ${inst.container_name}`);
            }
            if (prev.init_status !== init && init && init !== prev.init_status) {
              const level = init === "failed" ? "error" : "info";
              addDebugEntry(level, "Lifecycle", `${inst.node_id} init ${init}`, `Container: ${inst.container_name}`);
            }
          } else if (h) {
            addDebugEntry("info", "Lifecycle", `${inst.node_id} appeared (${h})`, `Container: ${inst.container_name}`);
          }
          prevInstances.current[inst.node_id] = { health: h, init_status: init };
        }
        // Detect removed containers
        for (const nodeId of Object.keys(prevInstances.current)) {
          if (!currentIds.has(nodeId)) {
            addDebugEntry("info", "Lifecycle", `${nodeId}: container removed`);
            delete prevInstances.current[nodeId];
          }
        }

        // Push health updates to diagram nodes
        const { updateNodeHealth } = useDiagramStore.getState();
        for (const inst of res.instances) {
          updateNodeHealth(inst.node_id, inst.health);
        }
        // Log errored containers
        for (const inst of res.instances) {
          if (inst.health === "error") {
            const details = [
              `Node: ${inst.node_id}`,
              `Container: ${inst.container_name}`,
              `Health: ${inst.health}`,
              `Init status: ${inst.init_status}`,
              `Demo: ${activeDemoId}`,
              `Tip: Open Admin panel → Logs tab to see container output`,
            ].join("\n");
            addDebugEntry("error", "Container", `${inst.node_id} entered error state`, details);
          }
        }
        // Update edge config status on diagram edges
        if (res.edge_configs && res.edge_configs.length > 0) {
          const { edges, setEdges } = useDiagramStore.getState();
          // Build lookup: backend edge IDs may have "-cluster" suffix from compose_generator
          const edgeConfigMap = new Map<string, { status: string; error: string }>();
          for (const ec of res.edge_configs) {
            const entry = { status: ec.status, error: ec.error || "" };
            edgeConfigMap.set(ec.edge_id, entry);
            // Strip trailing "-cluster" suffix(es) so frontend edge IDs match
            let stripped = ec.edge_id;
            while (stripped.endsWith("-cluster")) {
              stripped = stripped.slice(0, -8);
              edgeConfigMap.set(stripped, entry);
            }
          }
          const updated = edges.map((e) => {
            const entry = edgeConfigMap.get(e.id);
            const configStatus = entry?.status || (e.data as any)?.configStatus;
            const configError = entry?.error || (e.data as any)?.configError || "";
            if (configStatus && (configStatus !== (e.data as any)?.configStatus || configError !== (e.data as any)?.configError)) {
              return { ...e, data: { ...e.data, configStatus, configError } };
            }
            return e;
          });
          if (updated.some((e, i) => e !== edges[i])) {
            setEdges(updated);
          }
        }
        // Emit init script results to the Integrations tab (once per deploy)
        if (res.init_results && res.init_results.length > 0 && !initResultsEmitted.current.has(activeDemoId)) {
          initResultsEmitted.current.add(activeDemoId);
          const integScriptRe =
            /\b(mc|mcli|minio)\b|bucket|replicat|tier|ilm|lifecycle|site-replicat|admin\s+replicate|\bmb\b|\brb\b|\bversion\b|anonymous|encrypt|ilm\b/i;
          for (const result of res.init_results) {
            const level = result.exit_code === 0 ? "info" : "error";
            const output = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
            const script = String((result as any).script || (result as any).command || "").trim();
            addDebugEntry(level, "Provision", `${result.node_id}: init (exit ${result.exit_code})`, output || undefined);
            if (script && integScriptRe.test(script)) {
              const details = buildStructuredIntegrationDetails(
                script,
                output || "(no stdout/stderr)",
              );
              addDebugEntry(
                level,
                "Integration",
                `${result.node_id}: init script · exit ${result.exit_code}`,
                details,
              );
            }
          }
        }
        // Webhook / event-processor integration log (deduped by event id, TTL-scoped)
        const ie = res.integration_events;
        if (ie && ie.length > 0) {
          const now = Date.now();
          let seen = integrationEventSeen.current.get(activeDemoId);
          if (!seen) {
            seen = new Map<string, number>();
            integrationEventSeen.current.set(activeDemoId, seen);
          }
          for (const [k, ts] of [...seen.entries()]) {
            if (now - ts > DEBUG_LOG_TTL_MS) seen.delete(k);
          }
          for (const ev of ie) {
            const eid = typeof ev.id === "string" && ev.id ? ev.id : `${ev.ts_ms}-${ev.kind}-${ev.message}`;
            const tsMs = typeof ev.ts_ms === "number" ? ev.ts_ms : now;
            if (seen.has(eid)) continue;
            seen.set(eid, tsMs);
            const lvl = ev.level === "error" ? "error" : ev.level === "warn" ? "warn" : "info";
            const node = typeof ev.node_id === "string" && ev.node_id ? `${ev.node_id}: ` : "";
            const msg = typeof ev.message === "string" ? ev.message : String(ev.message ?? "");
            const kind = typeof ev.kind === "string" && ev.kind ? `${ev.kind} · ` : "";
            const outStr =
              typeof ev.details === "string" && ev.details.trim() ? ev.details.trim() : "";
            const cmdStr =
              typeof (ev as any).command === "string" && (ev as any).command.trim()
                ? String((ev as any).command).trim()
                : "";
            const structured = buildStructuredIntegrationDetails(
              cmdStr || undefined,
              outStr || undefined,
            );
            const ex =
              (ev as any).exit_code !== undefined && (ev as any).exit_code !== null
                ? ` · exit ${String((ev as any).exit_code)}`
                : "";
            addDebugEntry(lvl, "Integration", `${node}${kind}${msg}${ex}`, structured);
          }
        }
        // Update failover edge status
        getFailoverStatus(activeDemoId).then((fsRes) => {
          if (!fsRes.failover || fsRes.failover.length === 0) return;
          const { edges: currentEdges, setEdges: setCurrentEdges } = useDiagramStore.getState();
          let changed = false;
          const updatedEdges = currentEdges.map((e) => {
            const ed = e.data as any;
            if (ed?.connectionType !== "failover") return e;
            // Determine if this edge's target is the active upstream
            // Only match the failover entry whose gateway is this edge's source
            const sourceId = e.source;
            const targetId = e.target;
            const gwEntry = fsRes.failover.find((f) => f.gateway === sourceId);
            const isActive = !!(gwEntry && gwEntry.healthy && gwEntry.active_upstream && gwEntry.active_upstream.includes(targetId));
            if (ed.failoverActive !== isActive) {
              changed = true;
              return { ...e, data: { ...ed, failoverActive: isActive } };
            }
            return e;
          });
          if (changed) setCurrentEdges(updatedEdges);
        }).catch(() => {});
        // Poll resilience tester status
        getResilienceStatus(activeDemoId).then((rsRes) => {
          if (rsRes.probes && rsRes.probes.length > 0) {
            setResilienceProbes(rsRes.probes);
          }
        }).catch(() => {});
      }).catch((err: any) => {
        addDebugEntry("error", "Poll", "fetchInstances failed", err?.message || String(err));
      });
    syncInstances();
    const interval = setInterval(syncInstances, 5000);
    return () => clearInterval(interval);
  }, [activeDemoId, activeDemo?.status, setInstances]);

  // Fetch walkthrough steps when panel opens
  useEffect(() => {
    if (!walkthroughOpen || !activeDemoId) return;
    getWalkthrough(activeDemoId)
      .then((res) => setWalkthroughSteps(res.walkthrough))
      .catch(() => setWalkthroughSteps([]));
  }, [walkthroughOpen, activeDemoId]);

  const openTerminal = (nodeId: string) => {
    setTerminalTabs((prev) =>
      prev.find((t) => t.nodeId === nodeId) ? prev : [...prev, { nodeId }]
    );
  };

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startY = e.clientY;
    const startH = terminalHeight;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newH = Math.max(150, Math.min(800, startH + (startY - ev.clientY)));
      setTerminalHeight(newH);
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [terminalHeight]);

  const onLeftResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startX = e.clientX;
    const startW = leftPanelWidth;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newW = Math.max(150, Math.min(400, startW + (ev.clientX - startX)));
      setLeftPanelWidth(newW);
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [leftPanelWidth]);

  const onRightResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startX = e.clientX;
    const startW = rightPanelWidth;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const newW = Math.max(150, Math.min(400, startW + (startX - ev.clientX)));
      setRightPanelWidth(newW);
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [rightPanelWidth]);

  const isExperience = demos.find((d) => d.id === activeDemoId)?.mode === "experience";
  const isDemoRunning = activeDemo?.status === "running";
  // Palette only editable when definitively stopped — hide during deploying, running, stopping
  const isDemoEditable = !activeDemo?.status || activeDemo?.status === "not_deployed" || activeDemo?.status === "stopped" || activeDemo?.status === "error";
  const showSidebars = activeDemoId && activeView === "diagram";
  const showLeftSidebar = showSidebars && !isExperience && isDemoEditable;
  const showRightSidebar = showSidebars && !isExperience;
  const showWelcome = !activeDemoId;
  /** Terminal + Logs tabs (Lifecycle / Integrations) — dev and FA; standard uses toolbar Debug only. */
  const showDesignerLogsPanel = faMode === "dev" || faMode === "fa";

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <Toaster
        theme="dark"
        position="bottom-right"
        closeButton
        toastOptions={{
          style: { background: "#18181b", border: "1px solid #27272a", color: "#fafafa" },
          classNames: {
            error: "!border-red-800 !bg-red-950/90",
            actionButton: "!bg-zinc-700 !text-zinc-200 hover:!bg-zinc-600 !text-xs !px-2 !py-1",
          },
        }}
      />

      <AppNav />

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Home page — unmount on navigation so it re-fetches on return */}
        {currentPage === "home" && <HomePage />}

        {/* Designer - ALWAYS MOUNTED, hidden via display:none to preserve React Flow viewport state */}
        <div style={{ display: currentPage === "designer" ? "contents" : "none" }} className="flex flex-col h-full">
          {/* Top bar */}
          <Toolbar />

          {/* Deployment status bar — shown below toolbar when deploying/stopping/running-flash */}
          {activeDemoId && <DeployStatusBar demoId={activeDemoId} />}

          {/* Main area */}
          <div className="flex flex-1 min-h-0">
            {/* Left sidebar - Component Palette (hidden when running or in experience mode, but kept mounted to avoid re-fetching) */}
            {showSidebars && !isExperience && !layoutFocusMode && (
              <div className="flex-shrink-0 h-full" style={{ width: leftPanelWidth, display: isDemoEditable ? undefined : "none" }}>
                <ComponentPalette />
              </div>
            )}

            {/* Left resize handle */}
            {showLeftSidebar && !layoutFocusMode && (
              <div
                className="w-1 flex-shrink-0 bg-border hover:bg-primary/50 cursor-col-resize flex items-center justify-center"
                onMouseDown={onLeftResizeStart}
              >
                <div className="h-8 w-0.5 rounded-full bg-zinc-500" />
              </div>
            )}

            {/* Center content */}
            <div className="flex-1 min-w-0 h-full">
              {showWelcome ? (
                <WelcomeScreen />
              ) : activeView === "diagram" ? (
                <div className="relative w-full h-full">
                  <DiagramCanvas onOpenTerminal={openTerminal} />
                </div>
              ) : (
                <ControlPlane onOpenTerminal={openTerminal} />
              )}
            </div>

            {/* Right resize handle */}
            {showRightSidebar && !layoutFocusMode && (
              <div
                className="w-1 flex-shrink-0 bg-border hover:bg-primary/50 cursor-col-resize flex items-center justify-center"
                onMouseDown={onRightResizeStart}
              >
                <div className="h-8 w-0.5 rounded-full bg-zinc-500" />
              </div>
            )}

            {/* Right sidebar - Properties Panel (hidden in experience mode) */}
            {showRightSidebar && !layoutFocusMode && (
              <div className="flex-shrink-0 h-full" style={{ width: rightPanelWidth }}>
                {walkthroughOpen
                  ? <WalkthroughPanel steps={walkthroughSteps} onClose={() => setWalkthroughOpen(false)} />
                  : <PropertiesPanel />}
              </div>
            )}
          </div>

          {/* Floating Cockpit overlay */}
          {cockpitEnabled && activeDemoId && <CockpitOverlay />}

          {designerWebUiOverlay && (
            <DesignerWebUIOverlay
              proxyPath={designerWebUiOverlay.proxyPath}
              title={designerWebUiOverlay.title}
              onClose={() => setDesignerWebUiOverlay(null)}
            />
          )}

          {/* Bottom - Terminal / Logs panel (resizable) - only when demo selected */}
          {activeDemoId && !layoutFocusMode && (
            <div className="flex-shrink-0 flex flex-col" style={{ height: terminalHeight }}>
              <div
                className="h-2 bg-border hover:bg-primary/50 cursor-row-resize border-t border-border flex items-center justify-center flex-shrink-0"
                onMouseDown={onResizeStart}
              >
                <div className="w-8 h-0.5 rounded-full bg-zinc-500" />
              </div>
              {showDesignerLogsPanel && (
                <div className="flex items-center gap-0 px-2 bg-card border-b border-border flex-shrink-0">
                  {(["terminal", "logs"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setBottomTab(t)}
                      className={`px-3 py-1 text-[11px] font-medium transition-colors border-b-2 ${bottomTab === t ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                    >
                      {t === "terminal" ? "Terminal" : "Logs"}
                    </button>
                  ))}
                </div>
              )}
              <div className="flex-1 min-h-0">
                {showDesignerLogsPanel && bottomTab === "logs"
                  ? <DebugPanel />
                  : (debugOpen ? <DebugPanel /> : <TerminalPanel extraTabs={terminalTabs} />)
                }
              </div>
            </div>
          )}
        </div>

        {/* All non-designer pages unmount on navigation so they re-fetch fresh data on return */}
        {currentPage === "templates" && <TemplatesPage />}
        {currentPage === "images" && <ImagesPage />}
        {currentPage === "readiness" && useDemoStore.getState().faMode === "dev" && <ReadinessPage />}
        {currentPage === "fa-management" && useDemoStore.getState().faMode === "dev" && <FAManagementPage />}
        {currentPage === "connectivity" && <ConnectivityPage />}
        {currentPage === "settings" && <SettingsPage />}
      </main>
      {laserPointerMode && <LaserPointerOverlay />}
    </div>
  );
}

function LaserPointerOverlay() {
  const dotRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (dotRef.current) {
        dotRef.current.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
      }
      if (!visible) setVisible(true);
    };
    const onLeave = () => setVisible(false);
    const onEnter = () => setVisible(true);
    window.addEventListener("mousemove", onMove);
    document.documentElement.addEventListener("mouseleave", onLeave);
    document.documentElement.addEventListener("mouseenter", onEnter);
    return () => {
      window.removeEventListener("mousemove", onMove);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      document.documentElement.removeEventListener("mouseenter", onEnter);
    };
  }, [visible]);

  useEffect(() => {
    document.documentElement.classList.add("laser-pointer-active");
    return () => document.documentElement.classList.remove("laser-pointer-active");
  }, []);

  return (
    <div
      ref={dotRef}
      className="fixed top-0 left-0 pointer-events-none z-[99999]"
      style={{
        width: 16,
        height: 16,
        marginLeft: -8,
        marginTop: -8,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(239,68,68,0.95) 0%, rgba(239,68,68,0.6) 40%, rgba(239,68,68,0) 70%)",
        boxShadow: "0 0 8px 2px rgba(239,68,68,0.5), 0 0 20px 4px rgba(239,68,68,0.2)",
        opacity: visible ? 1 : 0,
        transition: "opacity 0.1s",
      }}
    />
  );
}
