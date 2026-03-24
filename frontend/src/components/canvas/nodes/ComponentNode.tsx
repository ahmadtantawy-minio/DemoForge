import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useEffect, useRef, useState } from "react";
import type { ComponentNodeData } from "../../../types";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { proxyUrl, execCommand } from "../../../api/client";
import ComponentIcon from "../../shared/ComponentIcon";

export default function ComponentNode({ id, data }: NodeProps) {
  const nodeData = data as unknown as ComponentNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, activeDemoId, demos, resilienceProbes } = useDemoStore();

  const isResilienceTester = nodeData.componentId === "resilience-tester";
  const isGenerator = nodeData.componentId === "file-generator" || nodeData.componentId === "data-generator";
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isRunning = activeDemo?.status === "running";

  // Poll generator process status
  const [genRunning, setGenRunning] = useState<boolean | null>(null);
  const genTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!activeDemoId || !isGenerator || !isRunning) {
      setGenRunning(null);
      return;
    }
    const poll = () => {
      execCommand(activeDemoId, id, "sh -c '[ -f /tmp/gen.pid ] && kill -0 $(cat /tmp/gen.pid) 2>/dev/null && echo RUNNING || echo IDLE'")
        .then((res) => setGenRunning(res.stdout.trim() === "RUNNING"))
        .catch(() => setGenRunning(null));
    };
    poll();
    genTimerRef.current = setInterval(poll, 5000);
    return () => { if (genTimerRef.current) clearInterval(genTimerRef.current); };
  }, [activeDemoId, id, isGenerator, isRunning]);

  const resilienceProbe = isResilienceTester ? resilienceProbes.find((p) => p.node_id === id) : null;

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
      window.open(proxyUrl(instance.web_uis[0].proxy_url), "_blank");
    }
  };

  const instance = instances.find((i) => i.node_id === id);
  const nodeIp = instance?.networks?.find((n) => n.ip_address)?.ip_address ?? null;
  const initStatus = (instance as any)?.init_status as string | undefined;

  return (
    <div
      className="bg-card border-2 border-border rounded-lg shadow-sm px-4 py-3 min-w-[140px] cursor-pointer hover:border-primary/50 transition-colors"
      onClick={() => setSelectedNode(id)}
      onDoubleClick={handleDoubleClick}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2">
        <ComponentIcon icon={nodeData.componentId} size={28} />
        <div>
          <div className="font-semibold text-sm text-foreground">{nodeData.displayName || nodeData.label}</div>
          <div className="text-xs text-muted-foreground">{nodeData.displayName ? nodeData.label : ""} {nodeData.variant}</div>
        </div>
        {nodeData.health && (
          <span
            className={`ml-auto w-2.5 h-2.5 rounded-full transition-colors duration-300 ${healthColors[nodeData.health] ?? "bg-muted-foreground"} ${nodeData.health === "starting" ? "animate-pulse" : ""}`}
            title={nodeData.health}
          />
        )}
      </div>
      {nodeIp && (
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

      {/* Generator status badge — live process check */}
      {isGenerator && isRunning && genRunning !== null && (
        <div className="mt-2 flex justify-center">
          {genRunning ? (
            <span className="text-xs font-semibold text-green-300 bg-green-950/60 border border-green-700/60 rounded-md px-2 py-1 leading-tight flex items-center gap-1.5 animate-pulse"
              title="Generating data — right-click to stop">
              <span className="w-2 h-2 rounded-full bg-green-400 shrink-0" />
              Generating...
            </span>
          ) : (
            <span className="text-xs font-semibold text-zinc-400 bg-zinc-900/60 border border-zinc-700/60 rounded-md px-2 py-1 leading-tight flex items-center gap-1.5"
              title="Idle — right-click to start generating">
              <span className="w-2 h-2 rounded-full bg-zinc-500 shrink-0" />
              Idle
            </span>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Right} />
    </div>
  );
}
