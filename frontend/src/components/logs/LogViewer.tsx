import { useEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { X, RefreshCw, CornerDownRight } from "lucide-react";
import { fetchContainerLogs, execContainerLog, fetchComponentManifest } from "../../api/client";

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

interface LogTab {
  name: string;
  command?: string; // undefined = docker logs
}

interface Props {
  demoId: string;
  nodeId: string;
  componentId?: string;
  onClose: () => void;
}

const DOCKER_TAB: LogTab = { name: "Docker Logs" };

export default function LogViewer({ demoId, nodeId, componentId, onClose }: Props) {
  const [tabs, setTabs] = useState<LogTab[]>([DOCKER_TAB]);
  const [activeTab, setActiveTab] = useState(0);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastFetch, setLastFetch] = useState<string>("");
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

  // Load log_commands from manifest
  useEffect(() => {
    if (!componentId) return;
    fetchComponentManifest(componentId)
      .then((manifest: any) => {
        if (manifest?.log_commands?.length) {
          setTabs([DOCKER_TAB, ...manifest.log_commands.map((lc: any) => ({ name: lc.name, command: lc.command }))]);
        }
      })
      .catch(() => {});
  }, [componentId]);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const tab = tabs[activeTab];
      let result: { lines: string[] };
      if (!tab.command) {
        result = await fetchContainerLogs(demoId, nodeId, 200, "60s");
      } else {
        result = await execContainerLog(demoId, nodeId, tab.command);
      }
      setLines(result.lines ?? []);
      setLastFetch(new Date().toLocaleTimeString());
    } catch (e: any) {
      setLines([`Error: ${e.message}`]);
    } finally {
      setLoading(false);
    }
  }, [demoId, nodeId, tabs, activeTab]);

  // Initial fetch + 3s polling
  useEffect(() => {
    fetchLogs();
    pollRef.current = setInterval(fetchLogs, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchLogs]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

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
          <div className="text-sm font-semibold text-foreground truncate">
            Logs — {nodeId}
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
              onClick={fetchLogs}
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
              key={tab.name}
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
          className="flex-1 overflow-y-auto p-2 pb-7 font-mono text-[11px] leading-relaxed text-green-400 bg-zinc-950 rounded-b-lg min-h-0"
        >
          {lines.length === 0 ? (
            <div className="text-muted-foreground text-center mt-8 text-xs">No output</div>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {line}
              </div>
            ))
          )}
        </div>

        {/* Line count — left side so it does not overlap the resize grip */}
        <div className="absolute bottom-2 left-3 text-[9px] text-muted-foreground pointer-events-none">
          {lines.length} lines
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
