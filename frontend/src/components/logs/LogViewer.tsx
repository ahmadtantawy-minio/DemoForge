import { useEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { X, RefreshCw, CornerDownRight } from "lucide-react";
import { fetchContainerLogs, execContainerLog, fetchComponentManifest, fetchInstances } from "../../api/client";
import {
  type IntegrationEventRow,
  mergePersistedIntegrationEvents,
  resolveIntegrationRunFingerprint,
  INTEGRATION_EVENTS_RETENTION_MS,
} from "../../lib/integrationEventsCache";

const STORAGE_KEY = "demoforge:logViewer:bounds";
const DEFAULT_WIDTH = 920;
const DEFAULT_HEIGHT = 560;
const MIN_WIDTH = 320;
const MIN_HEIGHT = 200;
const VIEW_MARGIN = 16;

interface PanelBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

function clampBounds(b: PanelBounds): PanelBounds {
  const maxW = Math.max(MIN_WIDTH, window.innerWidth - VIEW_MARGIN * 2);
  const maxH = Math.max(MIN_HEIGHT, window.innerHeight - VIEW_MARGIN * 2);
  const width = Math.min(Math.max(MIN_WIDTH, b.width), maxW);
  const height = Math.min(Math.max(MIN_HEIGHT, b.height), maxH);
  const x = Math.min(Math.max(VIEW_MARGIN, b.x), window.innerWidth - width - VIEW_MARGIN);
  const y = Math.min(Math.max(VIEW_MARGIN, b.y), window.innerHeight - height - VIEW_MARGIN);
  return { x, y, width, height };
}

function defaultBottomRightBounds(): PanelBounds {
  return clampBounds({
    x: Math.max(VIEW_MARGIN, window.innerWidth - DEFAULT_WIDTH - 24),
    y: Math.max(VIEW_MARGIN, window.innerHeight - DEFAULT_HEIGHT - 24),
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
  });
}

function loadStoredBounds(): PanelBounds {
  if (typeof window === "undefined") {
    return { x: VIEW_MARGIN, y: VIEW_MARGIN, width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultBottomRightBounds();
    const p = JSON.parse(raw) as Partial<PanelBounds>;
    if (
      typeof p.x === "number" &&
      typeof p.y === "number" &&
      typeof p.width === "number" &&
      typeof p.height === "number"
    ) {
      return clampBounds({ x: p.x, y: p.y, width: p.width, height: p.height });
    }
  } catch {
    /* ignore */
  }
  return defaultBottomRightBounds();
}

function persistBounds(b: PanelBounds) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(b));
  } catch {
    /* ignore */
  }
}

type LogTab =
  | { name: string; kind: "docker" }
  /** MinIO: lines from this container's stdout that mention the browser console / :9001 Web UI. */
  | { name: string; kind: "minio-console" }
  | { name: string; kind: "exec"; command: string }
  | { name: string; kind: "minio-config" };

type InitResultRow = {
  node_id: string;
  script: string;
  exit_code: number;
  stdout: string;
  stderr: string;
};

type EdgeConfigRow = {
  edge_id: string;
  connection_type: string;
  status: string;
  description: string;
  error: string;
};

/** Init scripts likely tied to MinIO Day0/1 (mc, buckets, replication, webhooks, etc.). */
function filterMinioRelatedInits(rows: InitResultRow[]): InitResultRow[] {
  return rows.filter((r) => {
    const idScript = `${r.node_id} ${r.script}`;
    if (/minio|mc-shell|mc[_-]|event-processor|register-webhook/i.test(idScript)) return true;
    const blob = `${r.script}\n${r.stdout}\n${r.stderr}`;
    if (
      /\b(mc|mcli|minio)\b|bucket|replicat|webhook|mirror|notify|site-replication|lambda|event[\s_-]?add|mb\s|rb\s|admin\s/i.test(
        blob
      )
    ) {
      return true;
    }
    return false;
  });
}

interface Props {
  demoId: string;
  nodeId: string;
  componentId?: string;
  onClose: () => void;
}

const DOCKER_TAB: LogTab = { name: "Docker Logs", kind: "docker" };
const MINIO_CONSOLE_TAB: LogTab = { name: "Console (Web UI)", kind: "minio-console" };
const MINIO_CONFIG_TAB: LogTab = { name: "Integrations", kind: "minio-config" };

/** Heuristic: MinIO process logs for the embedded browser console (port 9001 / WebUI). */
function lineLooksMinioConsoleRelated(line: string): boolean {
  return /console|WebUI|web ui|9001|:9001|browser ui|MINIO_BROWSER|subnet.*console|Listen.*9001|Starting.*console/i.test(line);
}

export default function LogViewer({ demoId, nodeId, componentId, onClose }: Props) {
  const [tabs, setTabs] = useState<LogTab[]>([DOCKER_TAB, MINIO_CONFIG_TAB]);
  const [activeTab, setActiveTab] = useState(0);
  const [lines, setLines] = useState<string[]>([]);
  const [minioSnapshot, setMinioSnapshot] = useState<{
    edge_configs: EdgeConfigRow[];
    init_results: InitResultRow[];
    integration_events: IntegrationEventRow[];
    error?: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastFetch, setLastFetch] = useState<string>("");
  // Active container — starts as the passed nodeId, can switch to sidecars
  const [activeNodeId, setActiveNodeId] = useState(nodeId);
  // Sidecar containers associated with the same demo
  const [sidecarNodes, setSidecarNodes] = useState<{ node_id: string; label: string }[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [bounds, setBounds] = useState<PanelBounds>(() => loadStoredBounds());
  const boundsRef = useRef(bounds);
  boundsRef.current = bounds;

  const dragRef = useRef<{ dragging: boolean; offsetX: number; offsetY: number }>({
    dragging: false,
    offsetX: 0,
    offsetY: 0,
  });
  const resizeRef = useRef<{
    resizing: boolean;
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  }>({
    resizing: false,
    startX: 0,
    startY: 0,
    startW: 0,
    startH: 0,
  });

  // Load log_commands from manifest (only for main service containers, not sidecars).
  // Re-run when switching back from a sidecar so MinIO-only tabs (e.g. console filter) return.
  useEffect(() => {
    if (!componentId) {
      setTabs([DOCKER_TAB, MINIO_CONFIG_TAB]);
      return;
    }
    if (activeNodeId !== nodeId) {
      setTabs([DOCKER_TAB, MINIO_CONFIG_TAB]);
      setActiveTab(0);
      return;
    }
    fetchComponentManifest(componentId)
      .then((manifest: any) => {
        const extra =
          manifest?.log_commands?.map((lc: any) => ({
            name: lc.name,
            kind: "exec" as const,
            command: lc.command,
          })) ?? [];
        const core =
          componentId === "minio"
            ? [DOCKER_TAB, MINIO_CONSOLE_TAB, MINIO_CONFIG_TAB, ...extra]
            : [DOCKER_TAB, MINIO_CONFIG_TAB, ...extra];
        setTabs(core);
      })
      .catch(() => {
        setTabs(componentId === "minio" ? [DOCKER_TAB, MINIO_CONSOLE_TAB, MINIO_CONFIG_TAB] : [DOCKER_TAB, MINIO_CONFIG_TAB]);
      });
  }, [componentId, activeNodeId, nodeId]);

  // Fetch sidecar containers for this demo so they can be selected in the log viewer
  useEffect(() => {
    fetchInstances(demoId)
      .then((resp) => {
        const sidecars = (resp.instances ?? [])
          .filter((i) => i.is_sidecar)
          .map((i) => ({ node_id: i.node_id, label: i.node_id }));
        setSidecarNodes(sidecars);
      })
      .catch(() => {});
  }, [demoId]);

  useEffect(() => {
    if (activeTab >= tabs.length) setActiveTab(0);
  }, [tabs, activeTab]);

  const activeTabKind = tabs[activeTab]?.kind;

  const refreshActiveTab = useCallback(async () => {
    const tab = tabs[activeTab];
    if (!tab) return;
    if (tab.kind === "minio-console") {
      setLoading(true);
      try {
        const result = await fetchContainerLogs(demoId, activeNodeId, 800, "120s");
        const raw = result.lines ?? [];
        const filtered = raw.filter(lineLooksMinioConsoleRelated);
        setLines(
          filtered.length > 0
            ? filtered
            : [
                "# No log lines matched the MinIO browser-console filter in this window.",
                "# Patterns include: console, WebUI, :9001, browser UI. Open “Docker Logs” for the full stream.",
              ]
        );
        setLastFetch(new Date().toLocaleTimeString());
      } catch (e: any) {
        setLines([`Error: ${e.message}`]);
      } finally {
        setLoading(false);
      }
      return;
    }
    if (tab.kind === "minio-config") {
      setLoading(true);
      try {
        const resp = await fetchInstances(demoId);
        const raw = resp.init_results ?? [];
        const instances = resp.instances ?? [];
        const runFp = resolveIntegrationRunFingerprint(demoId, instances);
        const integ = mergePersistedIntegrationEvents(demoId, runFp, resp.integration_events ?? []);
        setMinioSnapshot({
          edge_configs: resp.edge_configs ?? [],
          init_results: filterMinioRelatedInits(raw),
          integration_events: integ,
        });
        setLastFetch(new Date().toLocaleTimeString());
      } catch (e: any) {
        setMinioSnapshot({
          edge_configs: [],
          init_results: [],
          integration_events: [],
          error: e?.message ?? String(e),
        });
        setLastFetch(new Date().toLocaleTimeString());
      } finally {
        setLoading(false);
      }
      return;
    }
    setLoading(true);
    try {
      let result: { lines: string[] };
      if (tab.kind === "docker") {
        result = await fetchContainerLogs(demoId, activeNodeId, 200, "60s");
      } else {
        result = await execContainerLog(demoId, activeNodeId, tab.command);
      }
      setLines(result.lines ?? []);
      setLastFetch(new Date().toLocaleTimeString());
    } catch (e: any) {
      setLines([`Error: ${e.message}`]);
    } finally {
      setLoading(false);
    }
  }, [demoId, activeNodeId, tabs, activeTab]);

  // Initial fetch + polling (lighter interval for demo-wide MinIO snapshot)
  useEffect(() => {
    refreshActiveTab();
    const intervalMs = activeTabKind === "minio-config" ? 5000 : 3000; // docker, minio-console, exec
    pollRef.current = setInterval(refreshActiveTab, intervalMs);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshActiveTab, activeTabKind]);

  // Auto-scroll to bottom (docker / exec / minio-console tabs)
  useEffect(() => {
    if (activeTabKind === "minio-config") return;
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, activeTabKind]);

  // Keep panel in viewport when window resizes
  useEffect(() => {
    const handleResize = () => {
      setBounds((prev) => {
        const next = clampBounds(prev);
        if (next.x !== prev.x || next.y !== prev.y || next.width !== prev.width || next.height !== prev.height) {
          persistBounds(next);
          return next;
        }
        return prev;
      });
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const onHeaderMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    // Ignore clicks on action buttons inside header
    if ((e.target as HTMLElement).closest("button")) return;
    const b = boundsRef.current;
    dragRef.current = {
      dragging: true,
      offsetX: e.clientX - b.x,
      offsetY: e.clientY - b.y,
    };
  };

  const onResizeMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const b = boundsRef.current;
    resizeRef.current = {
      resizing: true,
      startX: e.clientX,
      startY: e.clientY,
      startW: b.width,
      startH: b.height,
    };
  };

  const snapBottomRight = () => {
    const next = defaultBottomRightBounds();
    setBounds(next);
    persistBounds(next);
  };

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (resizeRef.current.resizing) {
        const dx = e.clientX - resizeRef.current.startX;
        const dy = e.clientY - resizeRef.current.startY;
        const b = boundsRef.current;
        setBounds(
          clampBounds({
            ...b,
            width: resizeRef.current.startW + dx,
            height: resizeRef.current.startH + dy,
          })
        );
        return;
      }
      if (!dragRef.current.dragging) return;
      const b = boundsRef.current;
      const nextX = e.clientX - dragRef.current.offsetX;
      const nextY = e.clientY - dragRef.current.offsetY;
      setBounds(
        clampBounds({
          ...b,
          x: nextX,
          y: nextY,
        })
      );
    };
    const onMouseUp = () => {
      if (dragRef.current.dragging || resizeRef.current.resizing) {
        persistBounds(boundsRef.current);
      }
      dragRef.current.dragging = false;
      resizeRef.current.resizing = false;
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  return createPortal(
    <div className="fixed inset-0 z-[9999] pointer-events-none">
      <div
        className="pointer-events-auto bg-card border border-border rounded-lg shadow-2xl flex flex-col relative"
        style={{
          position: "fixed",
          left: bounds.x,
          top: bounds.y,
          width: bounds.width,
          height: bounds.height,
          maxWidth: "calc(100vw - 2rem)",
          maxHeight: "calc(100vh - 2rem)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0 cursor-move"
          onMouseDown={onHeaderMouseDown}
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-foreground truncate" title={activeNodeId}>
              Logs — {activeNodeId}
              {activeTabKind === "minio-config" && (
                <span className="text-[10px] font-normal text-muted-foreground ml-1">
                  (demo-wide: edges, init, webhooks; integration stream buffered ~{INTEGRATION_EVENTS_RETENTION_MS / 60_000}m locally)
                </span>
              )}
            </span>
            {sidecarNodes.length > 0 && (
              <select
                className="text-xs bg-accent/50 border border-border rounded px-1 py-0.5 text-foreground cursor-pointer shrink-0"
                value={activeNodeId}
                onChange={(e) => setActiveNodeId(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                title="Switch container"
              >
                <option value={nodeId}>{nodeId}</option>
                {sidecarNodes.map((s) => (
                  <option key={s.node_id} value={s.node_id}>{s.label}</option>
                ))}
              </select>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground">{lastFetch && `Updated ${lastFetch}`}</span>
            <button
              type="button"
              onClick={snapBottomRight}
              className="p-1 rounded hover:bg-accent transition-colors"
              title="Snap to bottom-right (default size)"
            >
              <CornerDownRight className="w-3.5 h-3.5 text-muted-foreground" />
            </button>
            <button
              type="button"
              onClick={refreshActiveTab}
              className="p-1 rounded hover:bg-accent transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-muted-foreground ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded hover:bg-accent transition-colors"
              title="Close"
            >
              <X className="w-3.5 h-3.5 text-muted-foreground" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-0.5 px-2 pt-1.5 border-b border-border shrink-0 overflow-x-auto">
          {tabs.map((tab, i) => (
            <button
              key={`${tab.kind}-${i}-${tab.name}`}
              onClick={() => setActiveTab(i)}
              className={`text-xs px-2.5 py-1 rounded-t border-b-2 whitespace-nowrap transition-colors ${
                activeTab === i
                  ? "border-primary text-foreground bg-accent/50"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/30"
              }`}
            >
              {tab.name}
            </button>
          ))}
        </div>

        {/* Log output */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto p-2 pb-7 font-mono text-[11px] leading-relaxed bg-zinc-950 rounded-b-lg min-h-0"
        >
          {activeTabKind === "minio-config" ? (
            <div className="text-zinc-200 space-y-4">
              {minioSnapshot?.error && (
                <div className="text-red-400 whitespace-pre-wrap">Error: {minioSnapshot.error}</div>
              )}
              {!minioSnapshot && loading && (
                <div className="text-muted-foreground text-center mt-8 text-xs">Loading integrations…</div>
              )}
              {minioSnapshot && !minioSnapshot.error && (
                <>
                  <section>
                    <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 mb-2">Edge automation (connections)</h3>
                    {minioSnapshot.edge_configs.length === 0 ? (
                      <div className="text-zinc-500 text-xs">No edge config records yet.</div>
                    ) : (
                      <ul className="space-y-2">
                        {minioSnapshot.edge_configs.map((ec) => (
                          <li
                            key={ec.edge_id}
                            className="border border-zinc-800 rounded p-2 bg-zinc-900/50"
                          >
                            <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline">
                              <span className="text-emerald-400/90">{ec.connection_type}</span>
                              <span className="text-zinc-500 text-[10px]">{ec.edge_id}</span>
                              <span
                                className={`text-[10px] ${
                                  ec.status === "ok" || ec.status === "active"
                                    ? "text-emerald-500"
                                    : ec.status === "pending" || ec.status === "paused"
                                      ? "text-amber-500"
                                      : "text-zinc-400"
                                }`}
                              >
                                {ec.status}
                              </span>
                            </div>
                            {ec.description ? (
                              <div className="text-zinc-400 mt-1 whitespace-pre-wrap">{ec.description}</div>
                            ) : null}
                            {ec.error ? (
                              <div className="text-red-400/90 mt-1 whitespace-pre-wrap text-[10px]">{ec.error}</div>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                  <section>
                    <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 mb-2">
                      Init scripts (mc / MinIO tooling)
                    </h3>
                    {minioSnapshot.init_results.length === 0 ? (
                      <div className="text-zinc-500 text-xs">
                        No matching init scripts. (Heuristic: mc, buckets, replication, webhooks, MinIO nodes.)
                      </div>
                    ) : (
                      <ul className="space-y-3">
                        {minioSnapshot.init_results.map((r, idx) => (
                          <li
                            key={`${r.node_id}-${r.script}-${idx}`}
                            className="border border-zinc-800 rounded p-2 bg-zinc-900/50"
                          >
                            <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline text-[10px] text-zinc-500">
                              <span className="text-cyan-400/90">{r.node_id}</span>
                              <span className="truncate max-w-full" title={r.script}>
                                {r.script}
                              </span>
                              <span className={r.exit_code === 0 ? "text-emerald-500" : "text-red-400"}>
                                exit {r.exit_code}
                              </span>
                            </div>
                            {r.stderr ? (
                              <pre className="text-red-400/80 mt-1 whitespace-pre-wrap break-all text-[10px] max-h-32 overflow-y-auto">
                                {r.stderr}
                              </pre>
                            ) : null}
                            {r.stdout ? (
                              <pre className="text-green-400/70 mt-1 whitespace-pre-wrap break-all text-[10px] max-h-48 overflow-y-auto">
                                {r.stdout.length > 8000 ? `…(truncated)\n${r.stdout.slice(-8000)}` : r.stdout}
                              </pre>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                  <section>
                    <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                      Webhook &amp; integration stream (event-processor)
                    </h3>
                    <p className="text-[10px] text-zinc-600 mb-2 leading-snug">
                      Merged with this browser&apos;s buffer: last {INTEGRATION_EVENTS_RETENTION_MS / 60_000} minutes of events
                      persist across refresh while this demo stack is the same run (localStorage + session).
                    </p>
                    {minioSnapshot.integration_events.length === 0 ? (
                      <div className="text-zinc-500 text-xs">
                        No integration log entries yet. Registration runs on deploy; deliveries appear when MinIO notifies the
                        processor.
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {minioSnapshot.integration_events.map((ev, idx) => {
                          const lvl = ev.level === "error" ? "text-red-400" : ev.level === "warn" ? "text-amber-400" : "text-zinc-300";
                          return (
                            <li
                              key={`${ev.id ?? idx}-${ev.ts_ms ?? idx}`}
                              className="border border-zinc-800 rounded p-2 bg-zinc-900/50"
                            >
                              <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline text-[10px] text-zinc-500">
                                {ev.node_id ? (
                                  <span className="text-cyan-400/90">{ev.node_id}</span>
                                ) : null}
                                {ev.kind ? <span className="text-violet-400/90">{ev.kind}</span> : null}
                                <span className={lvl}>{ev.message ?? ""}</span>
                              </div>
                              {ev.details ? (
                                <pre className="text-zinc-400/90 mt-1 whitespace-pre-wrap break-all text-[10px] max-h-40 overflow-y-auto">
                                  {ev.details}
                                </pre>
                              ) : null}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </section>
                </>
              )}
            </div>
          ) : lines.length === 0 && !loading ? (
            <div className="text-muted-foreground text-center mt-8 text-xs">No output</div>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all text-green-400">
                {line}
              </div>
            ))
          )}
        </div>

        {/* Line count — left side so it does not overlap the resize grip */}
        <div className="absolute bottom-2 left-3 text-[9px] text-muted-foreground pointer-events-none">
          {activeTabKind === "minio-config"
            ? minioSnapshot
              ? `${minioSnapshot.edge_configs.length} edges · ${minioSnapshot.init_results.length} inits · ${minioSnapshot.integration_events.length} integration`
              : ""
            : `${lines.length} lines`}
        </div>

        {/* Bottom-right resize handle */}
        <div
          role="presentation"
          className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize rounded-br-lg group"
          onMouseDown={onResizeMouseDown}
          title="Resize"
        >
          <span className="absolute bottom-1 right-1 block w-2.5 h-2.5 border-r-2 border-b-2 border-muted-foreground/60 group-hover:border-muted-foreground" />
        </div>
      </div>
    </div>,
    document.body
  );
}
