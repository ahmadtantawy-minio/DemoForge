import { useState } from "react";
import { createPortal } from "react-dom";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { stopInstance, startInstance } from "../../../api/client";
import { toast } from "sonner";
import ComponentIcon from "../../shared/ComponentIcon";

interface ClusterNodeData {
  label: string;
  componentId: string;
  nodeCount: number;
  drivesPerNode: number;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: string;
}

export default function ClusterNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as ClusterNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, activeDemoId, setActiveView } = useDemoStore();
  const nodeCount = nodeData.nodeCount || 4;
  const drivesPerNode = nodeData.drivesPerNode || 1;
  const [contextNode, setContextNode] = useState<{ idx: number; x: number; y: number } | null>(null);

  // Find running instances matching this cluster's synthetic nodes
  const clusterInstances = instances.filter((i) => i.node_id.startsWith(`${id}-node-`));
  const healthyCount = clusterInstances.filter((i) => i.health === "healthy").length;

  const handleNodeRightClick = (e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    e.stopPropagation();
    // Use nativeEvent to get correct viewport coordinates
    setContextNode({ idx, x: e.nativeEvent.clientX, y: e.nativeEvent.clientY });
  };

  const handleStopNode = async (nodeId: string) => {
    if (!activeDemoId) return;
    toast.info(`Stopping ${nodeId}...`);
    try {
      await stopInstance(activeDemoId, nodeId);
      toast.success(`${nodeId} stopped`);
    } catch (err: any) {
      toast.error(`Failed to stop ${nodeId}`, { description: err.message });
    }
    setContextNode(null);
  };

  const handleStartNode = async (nodeId: string) => {
    if (!activeDemoId) return;
    toast.info(`Starting ${nodeId}...`);
    try {
      await startInstance(activeDemoId, nodeId);
      toast.success(`${nodeId} started`);
    } catch (err: any) {
      toast.error(`Failed to start ${nodeId}`, { description: err.message });
    }
    setContextNode(null);
  };

  return (
    <>
      <NodeResizer isVisible={selected} minWidth={240} minHeight={160} />
      <div
        className="w-full h-full rounded-xl p-4 cursor-pointer border-2 border-primary/30 bg-primary/5"
        onClick={() => { setSelectedNode(id); setContextNode(null); }}
      >
        <Handle type="target" position={Position.Left} id="data-in" />
        {/* Cluster-level handles — both source+target at top and bottom for bidirectional dragging */}
        <Handle
          type="source"
          position={Position.Top}
          id="cluster-out"
          style={{ width: 12, height: 12, background: "#3b82f6", border: "2px solid #60a5fa", zIndex: 10 }}
          title="Cluster replication (drag to connect)"
        />
        <Handle
          type="target"
          position={Position.Top}
          id="cluster-in-top"
          style={{ width: 12, height: 12, background: "#3b82f6", border: "2px solid #60a5fa", zIndex: 10, opacity: 0 }}
        />
        <Handle
          type="target"
          position={Position.Bottom}
          id="cluster-in"
          style={{ width: 12, height: 12, background: "#3b82f6", border: "2px solid #60a5fa", zIndex: 10 }}
          title="Cluster replication (drag to connect)"
        />
        <Handle
          type="source"
          position={Position.Bottom}
          id="cluster-out-bottom"
          style={{ width: 12, height: 12, background: "#3b82f6", border: "2px solid #60a5fa", zIndex: 10, opacity: 0 }}
        />
        <div className="flex items-center gap-2 mb-3">
          <ComponentIcon icon={nodeData.componentId || "minio"} size={24} />
          <div className="flex-1">
            <div className="font-semibold text-sm text-foreground">
              {nodeData.label || "MinIO Cluster"}
            </div>
            <div className="text-[10px] text-muted-foreground">
              {nodeCount} nodes × {drivesPerNode} drive
              {drivesPerNode > 1 ? "s" : ""} • {nodeCount * drivesPerNode >= 4 ? "erasure coded" : "replicated"}
            </div>
          </div>
          {clusterInstances.length > 0 && (
            <div className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
              healthyCount === clusterInstances.length
                ? "bg-green-500/15 text-green-400"
                : healthyCount > 0
                ? "bg-yellow-500/15 text-yellow-400"
                : "bg-red-500/15 text-red-400"
            }`}>
              {healthyCount}/{clusterInstances.length}
            </div>
          )}
        </div>
        {/* Embedded NGINX LB */}
        {(() => {
          const lbId = `${id}-lb`;
          const lbInst = instances.find((i) => i.node_id === lbId);
          const lbHealthy = lbInst?.health === "healthy";
          // Console URL points through the backend proxy to the LB's console port
          const apiBase = (import.meta as any).env?.VITE_API_URL || "http://localhost:8000";
          const consoleUrl = lbInst ? `${apiBase}/proxy/${activeDemoId}/${lbId}/console/` : null;
          return (
            <div className="flex items-center gap-2 mb-2">
              <div
                className={`flex items-center gap-1.5 px-2 py-1 rounded border text-[10px] ${
                  lbInst
                    ? lbHealthy
                      ? "bg-green-500/10 border-green-500/30 text-green-400"
                      : lbInst.health === "starting"
                      ? "bg-yellow-500/10 border-yellow-500/30 text-yellow-400 animate-pulse"
                      : "bg-red-500/10 border-red-500/30 text-red-400"
                    : "bg-card border-border text-muted-foreground"
                }`}
                title={lbInst ? `${lbId} (${lbInst.health})` : "NGINX Load Balancer"}
              >
                <span className="font-bold">N</span>
                <span>LB</span>
              </div>
              {consoleUrl && activeDemoId && (
                <button
                  className="px-2 py-0.5 rounded border border-border bg-card text-[10px] text-foreground hover:bg-accent transition-colors"
                  onClick={(e) => {
                    e.stopPropagation();
                    window.open(consoleUrl, "_blank");
                  }}
                  title="Open MinIO Console (via LB)"
                >
                  Console
                </button>
              )}
            </div>
          );
        })()}
        {/* Internal node visualization */}
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: nodeCount }).map((_, i) => {
            const nodeId = `${id}-node-${i + 1}`;
            const inst = clusterInstances.find((c) => c.node_id === nodeId);
            const isHealthy = inst?.health === "healthy";
            const isStopped = inst?.health === "stopped";
            return (
              <div
                key={i}
                className={`w-8 h-8 rounded border flex items-center justify-center transition-colors cursor-pointer hover:border-primary ${
                  inst
                    ? isHealthy
                      ? "bg-green-500/10 border-green-500/30"
                      : isStopped
                      ? "bg-zinc-500/10 border-zinc-500/30 opacity-50"
                      : inst.health === "starting"
                      ? "bg-yellow-500/10 border-yellow-500/30 animate-pulse"
                      : "bg-red-500/10 border-red-500/30"
                    : "bg-card border-border"
                }`}
                title={inst ? `${nodeId} (${inst.health}) — right-click for actions` : `Node ${i + 1}`}
                onClick={(e) => { e.stopPropagation(); handleNodeRightClick(e, i); }}
                onContextMenu={(e) => handleNodeRightClick(e, i)}
              >
                <ComponentIcon
                  icon={nodeData.componentId || "minio"}
                  size={14}
                />
              </div>
            );
          })}
        </div>
        <Handle type="source" position={Position.Right} id="data-out" />
      </div>

      {/* Per-node context menu — portaled to body to escape React Flow transforms */}
      {contextNode && createPortal((() => {
        const nodeId = `${id}-node-${contextNode.idx + 1}`;
        const inst = clusterInstances.find((c) => c.node_id === nodeId);
        const isStopped = inst?.health === "stopped";
        return (
          <div
            className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[140px] text-popover-foreground"
            style={{ top: contextNode.y, left: contextNode.x }}
          >
            <div className="px-3 py-1 text-xs font-semibold text-muted-foreground border-b border-border">
              {nodeId}
            </div>
            {inst && !isStopped && (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                onClick={() => handleStopNode(nodeId)}
              >
                Stop Node
              </button>
            )}
            {inst && isStopped && (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-green-400 hover:bg-green-500/10 transition-colors"
                onClick={() => handleStartNode(nodeId)}
              >
                Start Node
              </button>
            )}
            {(() => {
              const lbId = `${id}-lb`;
              const lbInst = instances.find((i) => i.node_id === lbId);
              if (lbInst && lbInst.health === "healthy") {
                const apiBase = (import.meta as any).env?.VITE_API_URL || "http://localhost:8000";
                const url = `${apiBase}/proxy/${activeDemoId}/${lbId}/console/`;
                return (
                  <button
                    className="w-full text-left px-3 py-1.5 text-sm text-blue-400 hover:bg-blue-500/10 transition-colors"
                    onClick={() => { window.open(url, "_blank"); setContextNode(null); }}
                  >
                    Open Console
                  </button>
                );
              }
              return null;
            })()}
            <button
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
              onClick={() => { setActiveView("control-plane"); setContextNode(null); }}
            >
              View in Instances
            </button>
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
              onClick={() => setContextNode(null)}
            >
              Cancel
            </button>
          </div>
        );
      })(), document.body)}
    </>
  );
}
