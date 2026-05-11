import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import type { ComponentNodeData } from "../../../types";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { proxyUrl, execCommand, getGeneratorStatus } from "../../../api/client";
import ComponentIcon from "../../shared/ComponentIcon";

export default function ComponentNode({ id, data }: NodeProps) {
  const nodeData = data as unknown as ComponentNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const setEdges = useDiagramStore((s) => s.setEdges);
  const { instances, activeDemoId, demos, resilienceProbes } = useDemoStore();

  const isResilienceTester = nodeData.componentId === "resilience-tester";
  const isDataGenerator = nodeData.componentId === "data-generator";
  const isGenerator = nodeData.componentId === "file-generator" || isDataGenerator;
  const isRagApp = nodeData.componentId === "rag-app";
  const isOllama = nodeData.componentId === "ollama";
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isRunning = activeDemo?.status === "running";
  const isDeploying = activeDemo?.status === "deploying";

  // Poll generator process status
  const [genRunning, setGenRunning] = useState<boolean | null>(null);
  const [genStats, setGenStats] = useState<{ rows_per_sec: number; rows_generated: number; batches_sent: number } | null>(null);
  const genTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!activeDemoId || !isGenerator || !isRunning) {
      setGenRunning(null);
      setGenStats(null);
      return;
    }
    const poll = () => {
      if (isDataGenerator) {
        getGeneratorStatus(activeDemoId, id)
          .then((s) => {
            setGenRunning(s.state !== "idle");
            setGenStats({
              rows_per_sec: s.rows_per_sec ?? 0,
              rows_generated: s.rows_generated ?? 0,
              batches_sent: s.batches_sent ?? 0,
            });
          })
          .catch(() => { setGenRunning(null); setGenStats(null); });
      } else {
        execCommand(activeDemoId, id, "sh -c '[ -f /tmp/gen.pid ] && kill -0 $(cat /tmp/gen.pid) 2>/dev/null && echo RUNNING || echo IDLE'")
          .then((res) => setGenRunning(res.stdout.trim() === "RUNNING"))
          .catch(() => setGenRunning(null));
      }
    };
    poll();
    genTimerRef.current = setInterval(poll, 5000);
    return () => { if (genTimerRef.current) clearInterval(genTimerRef.current); };
  }, [activeDemoId, id, isGenerator, isDataGenerator, isRunning]);

  // Animate outgoing edges while generation is active
  useEffect(() => {
    if (!isGenerator) return;
    const currentEdges = useDiagramStore.getState().edges;
    setEdges(
      currentEdges.map((e) =>
        e.source === id
          ? { ...e, data: { ...e.data, status: genRunning ? "active" : "idle" } }
          : e
      )
    );
  }, [genRunning, isGenerator, id]);

  // Poll RAG app status
  const [ragStatus, setRagStatus] = useState<{ documents_ingested?: number; chunks_stored?: number } | null>(null);
  const ragTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!activeDemoId || !isRagApp || !isRunning) {
      setRagStatus(null);
      return;
    }
    const poll = () => {
      execCommand(activeDemoId, id, "wget -qO- http://localhost:8080/status 2>/dev/null")
        .then((res) => { if (res.exit_code === 0) setRagStatus(JSON.parse(res.stdout)); })
        .catch(() => setRagStatus(null));
    };
    poll();
    ragTimerRef.current = setInterval(poll, 8000);
    return () => { if (ragTimerRef.current) clearInterval(ragTimerRef.current); };
  }, [activeDemoId, id, isRagApp, isRunning]);

  // Poll Ollama models status
  const [ollamaReady, setOllamaReady] = useState<boolean | null>(null);
  const ollamaTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!activeDemoId || !isOllama || !isRunning) {
      setOllamaReady(null);
      return;
    }
    const poll = () => {
      execCommand(activeDemoId, id, "ollama list 2>/dev/null")
        .then((res) => {
          if (res.exit_code === 0) {
            const lines = res.stdout.trim().split("\n").slice(1);
            setOllamaReady(lines.length >= 2);
          } else {
            setOllamaReady(false);
          }
        })
        .catch(() => setOllamaReady(null));
    };
    poll();
    ollamaTimerRef.current = setInterval(poll, 10000);
    return () => { if (ollamaTimerRef.current) clearInterval(ollamaTimerRef.current); };
  }, [activeDemoId, id, isOllama, isRunning]);

  const resilienceProbe = isResilienceTester ? resilienceProbes.find((p) => p.node_id === id) : null;

  const solidToolingCard =
    nodeData.componentId === "external-system" ||
    nodeData.componentId === "event-processor" ||
    nodeData.componentId === "spark-etl-job";

  const healthColors: Record<string, string> = {
    healthy: "bg-green-500",
    starting: "bg-yellow-400",
    degraded: "bg-orange-400",
    error: "bg-red-500",
    stopped: "bg-muted-foreground",
  };

  const handleDoubleClick = () => {
    if (!activeDemoId) return;
    const instance = instances.find((i) => i.node_id === id);
    if (instance && instance.web_uis.length > 0) {
      const ui = instance.web_uis[0];
      if (nodeData.componentId === "event-processor") {
        useDiagramStore.getState().setDesignerWebUiOverlay({ proxyPath: ui.proxy_url, title: ui.name });
      } else {
        window.open(proxyUrl(ui.proxy_url), "_blank");
      }
    }
  };

  const instance = instances.find((i) => i.node_id === id);
  const nodeIp = instance?.networks?.find((n) => n.ip_address)?.ip_address ?? null;
  const initStatus = (instance as any)?.init_status as string | undefined;

  return (
    <div
      className={
        solidToolingCard
          ? "bg-white dark:bg-zinc-950 border-2 border-border rounded-lg shadow-md px-4 py-3 min-w-[140px] cursor-pointer hover:border-primary/50 transition-colors"
          : "bg-card border-2 border-border rounded-lg shadow-sm px-4 py-3 min-w-[140px] cursor-pointer hover:border-primary/50 transition-colors"
      }
      onClick={() => setSelectedNode(id)}
      onDoubleClick={handleDoubleClick}
    >
      {/* 4 visible handles — one source + one target per side, centered */}
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <Handle type="target" position={Position.Top} id="top" />
      <Handle type="source" position={Position.Top} id="top-out" className="!opacity-0 !w-0 !h-0 !min-w-0 !min-h-0" style={{ position: "absolute", top: 0, left: "50%" }} />
      <Handle type="source" position={Position.Bottom} id="bottom-out" />
      <Handle type="target" position={Position.Bottom} id="bottom-in" className="!opacity-0 !w-0 !h-0 !min-w-0 !min-h-0" style={{ position: "absolute", bottom: 0, left: "50%" }} />
      <div className="flex items-center gap-2">
        <ComponentIcon icon={nodeData.componentId} size={28} />
        <div>
          <div className="font-semibold text-sm text-foreground">{nodeData.displayName || nodeData.label}</div>
          <div className="text-xs text-muted-foreground">{nodeData.displayName ? nodeData.label : ""} {nodeData.variant}</div>
          {nodeData.componentId === "data-generator" && nodeData.config?.DG_SCENARIO && (
            <div className="text-[10px] text-muted-foreground/70 leading-tight mt-0.5">
              {{"ecommerce-orders": "E-commerce Orders", "iot-telemetry": "IoT Sensor Telemetry", "financial-txn": "Financial Transactions"}[nodeData.config.DG_SCENARIO] ?? nodeData.config.DG_SCENARIO}
            </div>
          )}
          {isRagApp && isRunning && ragStatus && (
            <div className="text-[10px] text-muted-foreground/70 leading-tight mt-0.5">
              {ragStatus.documents_ingested} docs / {ragStatus.chunks_stored} chunks
            </div>
          )}
          {isOllama && isRunning && ollamaReady !== null && (
            <div className="text-[10px] text-muted-foreground/70 leading-tight mt-0.5">
              {ollamaReady ? "Models ready" : "Downloading..."}
            </div>
          )}
        </div>
        {(isRunning || isDeploying) && (
          nodeData.health === "degraded" ? (
            <span className="ml-auto shrink-0" title="Tables not ready — start data generation to create them">
              <AlertTriangle className="w-4 h-4 text-orange-400" />
            </span>
          ) : nodeData.health ? (
            <span
              className={`ml-auto w-2.5 h-2.5 rounded-full transition-colors duration-300 ${healthColors[nodeData.health] ?? "bg-muted-foreground"} ${nodeData.health === "starting" || isDeploying && nodeData.health !== "healthy" ? "animate-pulse" : ""}`}
              title={nodeData.health}
            />
          ) : isDeploying ? (
            <span
              className="ml-auto w-2.5 h-2.5 rounded-full bg-yellow-400 animate-pulse"
              title="starting"
            />
          ) : null
        )}
      </div>
      {(isRunning || isDeploying) && nodeIp && (
        <div className="mt-1.5 flex justify-center">
          <span className="font-mono text-[10px] text-muted-foreground bg-muted/50 border border-border/50 rounded px-1.5 py-0.5 leading-none">
            {nodeIp}
          </span>
        </div>
      )}

      {/* Resilience Tester status badge */}
      {isResilienceTester && isRunning && resilienceProbe && resilienceProbe.status !== "unknown" && (
        <div className="mt-2 space-y-1">
          {resilienceProbe.status === "ok" ? (
            <>
              {resilienceProbe.upstream && (
                <div className="flex justify-center">
                  <span className="text-xs font-semibold text-blue-300 bg-blue-950/60 border border-blue-700/60 rounded-md px-2 py-1 leading-tight flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-blue-400 shrink-0" />
                    via {resilienceProbe.upstream}
                  </span>
                </div>
              )}
              <div className="flex justify-center">
                <span
                  className="text-xs font-semibold text-green-300 bg-green-950/60 border border-green-700/60 rounded-md px-2 py-1 leading-tight"
                  title={resilienceProbe.last_line}
                >
                  W:{resilienceProbe.write_ms}ms  R:{resilienceProbe.read_ms}ms  ·  {resilienceProbe.objects} obj
                </span>
              </div>
            </>
          ) : (
            <div className="flex justify-center">
              <span
                className="text-xs font-semibold text-red-300 bg-red-950/60 border border-red-700/60 rounded-md px-2 py-1 leading-tight flex items-center gap-1.5"
                title={resilienceProbe.last_line || "Probe failed"}
              >
                <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
                Probe failed{resilienceProbe.upstream ? ` — was via ${resilienceProbe.upstream}` : ""}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Generator status badge — live process check + rate metrics */}
      {isGenerator && isRunning && genRunning !== null && (
        <div className="mt-2 flex flex-col items-center gap-1">
          {genRunning ? (
            <span className="text-xs font-semibold text-green-300 bg-green-950/60 border border-green-700/60 rounded-md px-2 py-1 leading-tight flex items-center gap-1.5"
              title="Generating data — right-click to stop">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse shrink-0" />
              {genStats && genStats.rows_per_sec > 0
                ? `${genStats.rows_per_sec >= 1000 ? `${(genStats.rows_per_sec / 1000).toFixed(1)}k` : genStats.rows_per_sec.toFixed(0)} rows/s`
                : "Generating..."}
            </span>
          ) : (
            <span className="text-xs font-semibold text-zinc-400 bg-zinc-900/60 border border-zinc-700/60 rounded-md px-2 py-1 leading-tight flex items-center gap-1.5"
              title="Idle — right-click to start generating">
              <span className="w-2 h-2 rounded-full bg-zinc-500 shrink-0" />
              Idle
            </span>
          )}
          {genStats && genStats.rows_generated > 0 && (
            <span className="text-[10px] text-muted-foreground font-mono">
              {genStats.rows_generated >= 1_000_000
                ? `${(genStats.rows_generated / 1_000_000).toFixed(1)}M`
                : genStats.rows_generated >= 1000
                ? `${(genStats.rows_generated / 1000).toFixed(1)}k`
                : genStats.rows_generated} rows total
            </span>
          )}
        </div>
      )}

      {/* Right source handle is declared above (default, no id) */}
    </div>
  );
}
