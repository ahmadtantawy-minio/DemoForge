import { useState } from "react";
import { createPortal } from "react-dom";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { stopInstance, startInstance, resetCluster } from "../../../api/client";
import { toast } from "sonner";
import ComponentIcon from "../../shared/ComponentIcon";
import MinioAdminPanel from "../../minio/MinioAdminPanel";
import McpPanel from "../../minio/McpPanel";

interface ClusterNodeData {
  label: string;
  componentId: string;
  nodeCount: number;
  drivesPerNode: number;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: string;
  mcpEnabled?: boolean;
  aistorTablesEnabled?: boolean;
}

export default function ClusterNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as ClusterNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, activeDemoId, setActiveView } = useDemoStore();
  const nodeCount = nodeData.nodeCount || 4;
  const drivesPerNode = nodeData.drivesPerNode || 1;
  const [contextNode, setContextNode] = useState<{ idx: number; x: number; y: number } | null>(null);
  const [clusterMenu, setClusterMenu] = useState<{ x: number; y: number } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [adminPanelOpen, setAdminPanelOpen] = useState(false);
  const [adminDefaultTab, setAdminDefaultTab] = useState<"overview">("overview");
  const [mcpPanelOpen, setMcpPanelOpen] = useState(false);
  const [mcpDefaultTab, setMcpDefaultTab] = useState<"mcp-tools" | "ai-chat">("mcp-tools");
  const mcpEnabled = nodeData.mcpEnabled !== false;
  const aistorTablesEnabled = nodeData.aistorTablesEnabled === true;

  // Find running instances matching this cluster's synthetic nodes
  const clusterInstances = instances.filter((i) => i.node_id.startsWith(`${id}-node-`));
  const healthyCount = clusterInstances.filter((i) => i.health === "healthy").length;

  const handleNodeRightClick = (e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    e.stopPropagation();
    setConfirmReset(false);
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

  const handleResetCluster = async () => {
    if (!activeDemoId) return;
    setConfirmReset(false);
    setContextNode(null);
    toast.info(`Removing all buckets from ${nodeData.label || id}...`);
    try {
      const res = await resetCluster(activeDemoId, id);
      toast.success(`Cluster reset: ${res.buckets_removed} bucket${res.buckets_removed !== 1 ? "s" : ""} removed`);
    } catch (err: any) {
      const errMsg = err.message || "Unknown error";
      toast.error(`Failed to reset cluster`, {
        description: errMsg,
        duration: 10000,
        action: { label: "Copy", onClick: () => navigator.clipboard.writeText(errMsg) },
      });
    }
  };

  return (
    <>
      <NodeResizer isVisible={selected} minWidth={240} minHeight={160} />
      <div
        className="w-full h-full rounded-xl p-4 cursor-pointer border-2 border-primary/30 bg-primary/5"
        onClick={() => { setSelectedNode(id); setContextNode(null); setClusterMenu(null); }}
        onContextMenu={(e) => {
          // Only open cluster menu if not clicking on a node icon
          if ((e.target as HTMLElement).closest("[data-node-icon]")) return;
          e.preventDefault();
          e.stopPropagation();
          setClusterMenu({ x: e.clientX, y: e.clientY });
          setContextNode(null);
          setConfirmReset(false);
        }}
      >
        <Handle type="target" position={Position.Left} id="data-in" />
        <Handle type="target" position={Position.Top} id="data-in-top" className="!left-1/3 !w-0 !h-0 !border-0 !bg-transparent !min-w-0 !min-h-0" />
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
          const lbIp = lbInst?.networks?.find((n) => n.ip_address)?.ip_address ?? null;
          // Console URL points through the backend proxy to the LB's console port
          const apiBase = (import.meta as any).env?.VITE_API_URL || "http://localhost:9210";
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
              {lbIp && (
                <span className="font-mono text-[10px] text-muted-foreground bg-muted/50 border border-border/50 rounded px-1.5 py-0.5 leading-none">
                  {lbIp}
                </span>
              )}
              {mcpEnabled && (
                <span
                  className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-violet-500/15 text-violet-400 border border-violet-500/30"
                  title="MCP AI Tools enabled — right-click for AI Chat"
                >
                  MCP
                </span>
              )}
              {aistorTablesEnabled && (
                <span
                  className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-blue-700/15 text-blue-400 border border-blue-700/30"
                  title="AIStor Tables enabled — can connect directly to Trino"
                >
                  Tables
                </span>
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
            className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[220px] text-popover-foreground"
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
                const apiBase = (import.meta as any).env?.VITE_API_URL || "http://localhost:9210";
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
            {activeDemoId && (
              <>
              <div className="border-t border-border my-1" />
              {confirmReset ? (
                <div className="px-3 py-2">
                  <div className="text-xs text-destructive mb-2">Remove all buckets? This cannot be undone.</div>
                  <div className="flex gap-1">
                    <button
                      className="flex-1 text-xs px-2 py-1 rounded bg-destructive text-destructive-foreground hover:bg-destructive/80 transition-colors"
                      onClick={handleResetCluster}
                    >
                      Confirm Reset
                    </button>
                    <button
                      className="flex-1 text-xs px-2 py-1 rounded bg-muted text-muted-foreground hover:bg-accent transition-colors"
                      onClick={() => setConfirmReset(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                  onClick={() => setConfirmReset(true)}
                >
                  Reset Cluster (Remove All Buckets)
                </button>
              )}
              </>
            )}
            {activeDemoId && (
              <>
              <div className="border-t border-border my-1" />
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
                onClick={() => { setAdminDefaultTab("overview"); setAdminPanelOpen(true); setContextNode(null); }}
              >
                MinIO Admin
              </button>
              </>
            )}
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
              onClick={() => { setContextNode(null); }}
            >
              Cancel
            </button>
          </div>
        );
      })(), document.body)}

      {/* Cluster-level context menu */}
      {clusterMenu && createPortal(
        <div
          className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[220px] text-popover-foreground"
          style={{ top: Math.min(clusterMenu.y, window.innerHeight - 200), left: Math.min(clusterMenu.x, window.innerWidth - 240) }}
        >
          <div className="px-3 py-1 text-xs font-semibold text-muted-foreground border-b border-border">
            {nodeData.label || id}
          </div>
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
            onClick={() => { setAdminDefaultTab("overview"); setAdminPanelOpen(true); setClusterMenu(null); }}
          >
            MinIO Admin
          </button>
          {mcpEnabled && (
            <>
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
                onClick={() => { setMcpDefaultTab("mcp-tools"); setMcpPanelOpen(true); setClusterMenu(null); }}
              >
                MCP Tools
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
                onClick={() => { setMcpDefaultTab("ai-chat"); setMcpPanelOpen(true); setClusterMenu(null); }}
              >
                AI Chat
              </button>
            </>
          )}
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
            onClick={() => { setActiveView("control-plane"); setClusterMenu(null); }}
          >
            View in Instances
          </button>
          {activeDemoId && (
            <>
              <div className="border-t border-border my-1" />
              {confirmReset ? (
                <div className="px-3 py-2">
                  <div className="text-xs text-destructive mb-2">Remove all buckets from this cluster? This cannot be undone.</div>
                  <div className="flex gap-1">
                    <button
                      className="flex-1 text-xs px-2 py-1 rounded bg-destructive text-destructive-foreground hover:bg-destructive/80 transition-colors"
                      onClick={() => { handleResetCluster(); setClusterMenu(null); }}
                    >
                      Confirm Reset
                    </button>
                    <button
                      className="flex-1 text-xs px-2 py-1 rounded bg-muted text-muted-foreground hover:bg-accent transition-colors"
                      onClick={() => setConfirmReset(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                  onClick={() => setConfirmReset(true)}
                >
                  Reset Cluster (Remove All Buckets)
                </button>
              )}
            </>
          )}
          <div className="border-t border-border my-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
            onClick={() => setClusterMenu(null)}
          >
            Cancel
          </button>
        </div>,
        document.body
      )}

      {/* MinIO Admin Panel */}
      <MinioAdminPanel
        open={adminPanelOpen}
        onOpenChange={setAdminPanelOpen}
        clusterId={id}
        clusterLabel={nodeData.label || "MinIO Cluster"}
        defaultTab={adminDefaultTab}
      />

      {mcpPanelOpen && activeDemoId && (
        <McpPanel
          open={mcpPanelOpen}
          onOpenChange={setMcpPanelOpen}
          demoId={activeDemoId}
          clusterId={id}
          clusterLabel={nodeData.label || "MinIO Cluster"}
          defaultTab={mcpDefaultTab}
        />
      )}
    </>
  );
}
