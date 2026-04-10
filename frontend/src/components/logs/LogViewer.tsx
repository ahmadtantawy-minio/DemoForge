import { useEffect, useRef, useState, useCallback } from "react";
import { X, RefreshCw } from "lucide-react";
import { fetchContainerLogs, execContainerLog, fetchComponentManifest } from "../../api/client";

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

  return (
    <div className="fixed inset-0 z-[9999] flex items-end justify-end p-4 pointer-events-none">
      <div className="pointer-events-auto bg-card border border-border rounded-lg shadow-2xl flex flex-col"
        style={{ width: 640, height: 480, maxWidth: "calc(100vw - 2rem)", maxHeight: "calc(100vh - 4rem)" }}>
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
          <div className="text-sm font-semibold text-foreground truncate">
            Logs — {nodeId}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground">{lastFetch && `Updated ${lastFetch}`}</span>
            <button
              onClick={fetchLogs}
              className="p-1 rounded hover:bg-accent transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-muted-foreground ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
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
          className="flex-1 overflow-y-auto p-2 font-mono text-[11px] leading-relaxed text-green-400 bg-zinc-950 rounded-b-lg"
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

        {/* Badge */}
        <div className="absolute bottom-2 right-3 text-[9px] text-muted-foreground pointer-events-none">
          {lines.length} lines
        </div>
      </div>
    </div>
  );
}
