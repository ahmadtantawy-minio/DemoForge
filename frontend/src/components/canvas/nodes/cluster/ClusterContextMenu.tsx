import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { ClusterNodeData, ContainerInstance } from "../../../../types";

interface Props {
  type: "cluster" | "node" | "pool";
  nodeIdx?: number;
  poolId?: string;
  x: number;
  y: number;
  clusterId: string;
  clusterData: ClusterNodeData;
  isRunning: boolean;
  demoId: string | null;
  instances: ContainerInstance[];
  consoleUrl: string | null;
  driveSubmenu: number | null;
  onSetDriveSubmenu: (idx: number | null) => void;
  onClose: () => void;
  onOpenAdmin: (tab: "overview" | "logs") => void;
  onOpenMcp: (tab: "mcp-tools" | "ai-chat") => void;
  onStopNode: (nodeId: string) => void;
  onStartNode: (nodeId: string) => void;
  onStopDrive: (nodeId: string, driveNum: number) => void;
  onStartDrive: (nodeId: string, driveNum: number) => void;
  onResetCluster: () => void;
  onDeleteCluster: () => void;
  onViewInstances: () => void;
  onEditCluster: () => void;
  onAddPool: () => void;
  onEditPool: (poolId: string) => void;
  onDuplicatePool: (poolId: string) => void;
  onRemovePool: (poolId: string) => void;
  onViewNodeDetails: (poolId: string, nodeIndex: number) => void;
  poolsCount: number;
  confirmReset: boolean;
  onSetConfirmReset: (v: boolean) => void;
  confirmDelete: boolean;
  onSetConfirmDelete: (v: boolean) => void;
  confirmRemovePool: boolean;
  onSetConfirmRemovePool: (v: boolean) => void;
}

export default function ClusterContextMenu(props: Props) {
  const {
    type,
    nodeIdx,
    poolId,
    x,
    y,
    clusterId,
    clusterData,
    isRunning,
    demoId,
    instances,
    consoleUrl,
    driveSubmenu,
    onSetDriveSubmenu,
    onClose,
    onOpenAdmin,
    onOpenMcp,
    onStopNode,
    onStartNode,
    onStopDrive,
    onStartDrive,
    onResetCluster,
    onDeleteCluster,
    onViewInstances,
    onEditCluster,
    onAddPool,
    onEditPool,
    onDuplicatePool,
    onRemovePool,
    onViewNodeDetails,
    poolsCount,
    confirmReset,
    onSetConfirmReset,
    confirmDelete,
    onSetConfirmDelete,
    confirmRemovePool,
    onSetConfirmRemovePool,
  } = props;

  const menuRef = useRef<HTMLDivElement>(null);
  const pools = clusterData.serverPools || [];
  const isAIStor = (clusterData.config?.MINIO_EDITION || "ce") === "aistor";
  const mcpEnabled = isAIStor && clusterData.mcpEnabled !== false;

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  // Resolve node ID for node-type menu
  let nodeId = "";
  let nodeInstance: ContainerInstance | undefined;
  let drivesPerNode = 1;
  let nodePoolId = "";
  let nodePoolNodeIndex = 0;
  if (type === "node" && nodeIdx !== undefined) {
    // Find which pool this nodeIdx belongs to (flat index across pools)
    let remaining = nodeIdx;
    let poolIdx = 0;
    for (let i = 0; i < pools.length; i++) {
      if (remaining < pools[i].nodeCount) {
        poolIdx = i;
        break;
      }
      remaining -= pools[i].nodeCount;
    }
    const pool = pools[poolIdx];
    drivesPerNode = pool?.drivesPerNode ?? 1;
    nodePoolId = pool?.id ?? "";
    nodePoolNodeIndex = remaining + 1;
    nodeId =
      pools.length === 1
        ? `${clusterId}-node-${remaining + 1}`
        : `${clusterId}-pool${poolIdx + 1}-node-${remaining + 1}`;
    nodeInstance = instances.find((i) => i.node_id === nodeId);
  }

  const style: React.CSSProperties = {
    top: Math.min(y, window.innerHeight - 200),
    left: Math.min(x, window.innerWidth - 240),
  };

  if (type === "node") {
    const isStopped = nodeInstance?.health === "stopped";

    // Config-time node menu
    if (!isRunning) {
      const menu = (
        <div
          ref={menuRef}
          className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[220px] text-popover-foreground"
          style={style}
        >
          <div className="px-3 py-1 text-xs font-semibold text-muted-foreground border-b border-border">
            {nodeId}
          </div>
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
            onClick={() => onViewNodeDetails(nodePoolId, nodePoolNodeIndex)}
          >
            View node details
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground opacity-50 cursor-not-allowed"
            disabled
            title="Deploy the cluster first"
          >
            View logs (deploy first)
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground opacity-50 cursor-not-allowed"
            disabled
            title="Deploy the cluster first"
          >
            Open terminal (deploy first)
          </button>
          <div className="border-t border-border my-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      );
      return createPortal(menu, document.body);
    }

    const menu = (
      <div
        ref={menuRef}
        className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[220px] text-popover-foreground"
        style={style}
      >
        <div className="px-3 py-1 text-xs font-semibold text-muted-foreground border-b border-border">
          {nodeId}
        </div>
        {nodeInstance && !isStopped && (
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
            onClick={() => onStopNode(nodeId)}
          >
            Stop Node
          </button>
        )}
        {nodeInstance && isStopped && (
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-green-400 hover:bg-green-500/10 transition-colors"
            onClick={() => onStartNode(nodeId)}
          >
            Start Node
          </button>
        )}
        {nodeInstance && !isStopped && drivesPerNode > 1 && (
          <>
            <button
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors flex items-center justify-between"
              onClick={() =>
                onSetDriveSubmenu(driveSubmenu === nodeIdx ? null : nodeIdx ?? null)
              }
            >
              <span>
                Drives ({drivesPerNode - (nodeInstance.stopped_drives?.length ?? 0)}/{drivesPerNode} online)
              </span>
              <span className="text-muted-foreground text-xs">
                {driveSubmenu === nodeIdx ? "▲" : "▼"}
              </span>
            </button>
            {driveSubmenu === nodeIdx && (
              <div className="px-2 py-1 grid grid-cols-4 gap-1">
                {Array.from({ length: drivesPerNode }).map((_, d) => {
                  const driveNum = d + 1;
                  const isDriveStopped = nodeInstance!.stopped_drives?.includes(driveNum) ?? false;
                  return (
                    <button
                      key={driveNum}
                      title={
                        isDriveStopped
                          ? `Drive ${driveNum} offline — click to restore`
                          : `Drive ${driveNum} online — click to stop`
                      }
                      className={`text-[10px] py-0.5 rounded border transition-colors ${
                        isDriveStopped
                          ? "border-orange-500/50 bg-orange-500/10 text-orange-300 hover:bg-orange-500/20"
                          : "border-green-500/30 bg-green-500/10 text-green-300 hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-300"
                      }`}
                      onClick={() =>
                        isDriveStopped
                          ? onStartDrive(nodeId, driveNum)
                          : onStopDrive(nodeId, driveNum)
                      }
                    >
                      d{driveNum}
                    </button>
                  );
                })}
              </div>
            )}
          </>
        )}
        {consoleUrl && (
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-blue-400 hover:bg-blue-500/10 transition-colors"
            onClick={() => {
              window.open(consoleUrl, "_blank");
              onClose();
            }}
          >
            Open Console
          </button>
        )}
        <button
          className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
          onClick={onViewInstances}
        >
          View in Instances
        </button>
        {demoId && (
          <>
            <div className="border-t border-border my-1" />
            {confirmReset ? (
              <div className="px-3 py-2">
                <div className="text-xs text-destructive mb-2">
                  Remove all buckets? This cannot be undone.
                </div>
                <div className="flex gap-1">
                  <button
                    className="flex-1 text-xs px-2 py-1 rounded bg-destructive text-destructive-foreground hover:bg-destructive/80 transition-colors"
                    onClick={onResetCluster}
                  >
                    Confirm Reset
                  </button>
                  <button
                    className="flex-1 text-xs px-2 py-1 rounded bg-muted text-muted-foreground hover:bg-accent transition-colors"
                    onClick={() => onSetConfirmReset(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                onClick={() => onSetConfirmReset(true)}
              >
                Reset Cluster (Remove All Buckets)
              </button>
            )}
            <div className="border-t border-border my-1" />
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
              onClick={() => onOpenAdmin("overview")}
            >
              MinIO Admin
            </button>
          </>
        )}
        <button
          className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
          onClick={onClose}
        >
          Cancel
        </button>
      </div>
    );
    return createPortal(menu, document.body);
  }

  // Pool menu is config-time only; at runtime pool right-click falls through to cluster menu
  if (type === "pool" && !isRunning) {
    const activePool = pools.find((p) => p.id === poolId);
    const onlyPool = poolsCount <= 1;
    const menu = (
      <div
        ref={menuRef}
        className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[220px] text-popover-foreground"
        style={style}
      >
        <div className="px-3 py-1 text-xs font-semibold text-muted-foreground border-b border-border">
          {activePool?.id || "Pool"}
        </div>
        <button
          className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
          onClick={() => poolId && onEditPool(poolId)}
        >
          Edit pool config
        </button>
        <button
          className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
          onClick={() => poolId && onDuplicatePool(poolId)}
        >
          Duplicate pool
        </button>
        <div className="border-t border-border my-1" />
        {onlyPool ? (
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground opacity-50 cursor-not-allowed"
            disabled
            title="Cannot remove the only pool"
          >
            Remove pool (only pool)
          </button>
        ) : confirmRemovePool ? (
          <div className="px-3 py-2">
            <div className="text-xs text-destructive mb-2">
              Remove this pool? This cannot be undone.
            </div>
            <div className="flex gap-1">
              <button
                className="flex-1 text-xs px-2 py-1 rounded bg-destructive text-destructive-foreground hover:bg-destructive/80 transition-colors"
                onClick={() => poolId && onRemovePool(poolId)}
              >
                Confirm Remove
              </button>
              <button
                className="flex-1 text-xs px-2 py-1 rounded bg-muted text-muted-foreground hover:bg-accent transition-colors"
                onClick={() => onSetConfirmRemovePool(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
            onClick={() => onSetConfirmRemovePool(true)}
          >
            Remove pool
          </button>
        )}
        <div className="border-t border-border my-1" />
        <button
          className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
          onClick={onClose}
        >
          Cancel
        </button>
      </div>
    );
    return createPortal(menu, document.body);
  }

  const menu = (
    <div
      ref={menuRef}
      className="fixed z-[9999] bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[220px] text-popover-foreground"
      style={style}
    >
      <div className="px-3 py-1 text-xs font-semibold text-muted-foreground border-b border-border">
        {clusterData.label || clusterId}
      </div>
      {isRunning ? (
        <>
          {consoleUrl && (
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-blue-400 hover:bg-blue-500/10 transition-colors"
              onClick={() => {
                window.open(consoleUrl, "_blank");
                onClose();
              }}
            >
              MinIO Console
            </button>
          )}
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
            onClick={() => onOpenAdmin("overview")}
          >
            MinIO Admin
          </button>
          {mcpEnabled && (
            <>
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
                onClick={() => onOpenMcp("mcp-tools")}
              >
                MCP Tools
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
                onClick={() => onOpenMcp("ai-chat")}
              >
                AI Chat
              </button>
            </>
          )}
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
            onClick={onViewInstances}
          >
            View in Instances
          </button>
          {demoId && (
            <>
              <div className="border-t border-border my-1" />
              {confirmReset ? (
                <div className="px-3 py-2">
                  <div className="text-xs text-destructive mb-2">
                    Remove all buckets from this cluster? This cannot be undone.
                  </div>
                  <div className="flex gap-1">
                    <button
                      className="flex-1 text-xs px-2 py-1 rounded bg-destructive text-destructive-foreground hover:bg-destructive/80 transition-colors"
                      onClick={onResetCluster}
                    >
                      Confirm Reset
                    </button>
                    <button
                      className="flex-1 text-xs px-2 py-1 rounded bg-muted text-muted-foreground hover:bg-accent transition-colors"
                      onClick={() => onSetConfirmReset(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                  onClick={() => onSetConfirmReset(true)}
                >
                  Reset Cluster (Remove All Buckets)
                </button>
              )}
            </>
          )}
        </>
      ) : (
        <>
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
            onClick={onEditCluster}
          >
            Edit cluster settings
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent transition-colors"
            onClick={onAddPool}
          >
            Add server pool
          </button>
          <div className="border-t border-border my-1" />
          {!confirmDelete ? (
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
              onClick={() => onSetConfirmDelete(true)}
            >
              Delete cluster
            </button>
          ) : (
            <div className="px-3 py-1.5 flex items-center gap-2">
              <span className="text-xs text-destructive">Delete?</span>
              <button
                className="px-2 py-0.5 text-xs bg-destructive text-destructive-foreground rounded hover:bg-destructive/80"
                onClick={onDeleteCluster}
              >
                Yes
              </button>
              <button
                className="px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded hover:bg-accent"
                onClick={() => onSetConfirmDelete(false)}
              >
                No
              </button>
            </div>
          )}
        </>
      )}
      <div className="border-t border-border my-1" />
      <button
        className="w-full text-left px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent transition-colors"
        onClick={onClose}
      >
        Cancel
      </button>
    </div>
  );
  return createPortal(menu, document.body);
}
