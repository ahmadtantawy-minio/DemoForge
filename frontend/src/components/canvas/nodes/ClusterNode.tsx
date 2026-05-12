import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { Handle, Position, type NodeProps, useUpdateNodeInternals } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import {
  stopInstance,
  startInstance,
  resetCluster,
  stopDrive,
  startDrive,
  startPoolDecommission,
  cancelPoolDecommission,
  getPoolDecommissionStatus,
} from "../../../api/client";
import { saveDiagramAndApplyClusterTopology } from "../../../lib/persistClusterTopology";
import { toast } from "../../../lib/toast";
import { migrateClusterData } from "../../../lib/clusterMigration";
import { getClusterInstances, getPoolInstances, computeClusterAggregates } from "../../../lib/clusterUtils";
import ClusterHeader from "./cluster/ClusterHeader";
import FeatureBadges from "./cluster/FeatureBadges";
import PoolContainer from "./cluster/PoolContainer";
import NodeTile from "./cluster/NodeTile";
import CapacityBar from "./cluster/CapacityBar";
import AddPoolButton from "./cluster/AddPoolButton";
import AddPoolDialog from "./cluster/AddPoolDialog";
import ClusterContextMenu from "./cluster/ClusterContextMenu";
import MinioAdminPanel from "../../minio/MinioAdminPanel";
import McpPanel from "../../minio/McpPanel";
import LogViewer from "../../logs/LogViewer";
import { apiUrl } from "../../../lib/apiBase";
import { CLUSTER_EDGE_TYPES } from "../../../lib/clusterConnectionAnchors";
import type { MinioServerPool } from "../../../types";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

type PoolDialogState =
  | { mode: "closed" }
  | { mode: "add" }
  | { mode: "duplicate"; duplicateSourceId: string };

export default function ClusterNode({ id, data }: NodeProps) {
  const nodeRef = useRef<HTMLDivElement>(null);
  const updateNodeInternals = useUpdateNodeInternals();
  const nodeData = migrateClusterData(data);
  const pools = nodeData.serverPools || [];
  const {
    setSelectedNode,
    setSelectedClusterElement,
    selectedClusterElement,
    nodes,
    edges,
    setNodes,
    setClipboard,
    openEditorDeleteDialog,
    reanchorClusterEdges,
    reanchorAllClusterToClusterEdges,
    setDirty,
  } = useDiagramStore();
  const { instances, clusterHealth, activeDemoId, demos, setActiveView } = useDemoStore();
  const demoStatus = demos.find((d) => d.id === activeDemoId)?.status;
  const isRunning = demoStatus === "running";
  const isEditable = demoStatus === "not_deployed" || demoStatus === "stopped" || demoStatus == null;
  const clusterStatus = isRunning ? (clusterHealth[id] ?? null) : null;
  const clusterInstances = getClusterInstances(instances, id);
  const aggregates = computeClusterAggregates(pools);
  const isAIStor = (nodeData.config?.MINIO_EDITION || "ce") === "aistor";
  const mcpEnabled = isAIStor && nodeData.mcpEnabled !== false;
  const aistorTablesEnabled = isAIStor && nodeData.aistorTablesEnabled === true;

  const _lbInst = instances.find((i) => i.node_id === `${id}-lb`);
  const consoleUrl =
    _lbInst?.health === "healthy" && activeDemoId
      ? apiUrl(`/proxy/${activeDemoId}/${id}-lb/console/`)
      : null;

  const [contextMenu, setContextMenu] = useState<{
    type: "cluster" | "node" | "pool";
    nodeIdx?: number;
    poolId?: string;
    x: number;
    y: number;
  } | null>(null);
  const [driveSubmenu, setDriveSubmenu] = useState<number | null>(null);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [removePoolTarget, setRemovePoolTarget] = useState<string | null>(null);
  const [adminPanelOpen, setAdminPanelOpen] = useState(false);
  const [adminDefaultTab, setAdminDefaultTab] = useState<"overview" | "logs">("overview");
  const [mcpPanelOpen, setMcpPanelOpen] = useState(false);
  const [mcpDefaultTab, setMcpDefaultTab] = useState<"mcp-tools" | "ai-chat">("mcp-tools");
  const [logViewerNodeId, setLogViewerNodeId] = useState<string | null>(null);
  const [poolDecommissionStatus, setPoolDecommissionStatus] = useState<Record<string, "active" | "decommissioning" | "decommissioned">>({});
  const [poolDecommissionDetail, setPoolDecommissionDetail] = useState<Record<string, string>>({});
  const [poolDialog, setPoolDialog] = useState<PoolDialogState>({ mode: "closed" });

  // Close context menu when canvas background is clicked
  useEffect(() => {
    const handler = () => setContextMenu(null);
    window.addEventListener("canvas:close-menus", handler);
    return () => window.removeEventListener("canvas:close-menus", handler);
  }, []);

  // Refresh handle positions whenever the node resizes (instances, health, pool edits).
  // We use ResizeObserver only — no RAF. rAF fires before ResizeObserver in the browser
  // event loop, meaning an rAF-triggered updateNodeInternals would run before ReactFlow's
  // own ResizeObserver has measured the node height, causing handles to be placed at wrong
  // positions. ReactFlow registers its ResizeObserver first (on mount), so its callback
  // fires before ours, ensuring dimensions are correct when we call updateNodeInternals.
  useEffect(() => {
    const el = nodeRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => updateNodeInternals(id));
    observer.observe(el);
    return () => observer.disconnect();
  }, [id, updateNodeInternals, instances, clusterHealth]);

  const persistPoolChangeAndApply = useCallback(
    (newNodes: typeof nodes) => {
      if (!activeDemoId || !isRunning) return Promise.resolve();
      return saveDiagramAndApplyClusterTopology(activeDemoId, id, newNodes, edges);
    },
    [activeDemoId, isRunning, edges, id]
  );

  const handleToggleExtraClusterConnectors = useCallback(() => {
    const next = !nodeData.showExtraClusterConnectors;
    setNodes(
      nodes.map((n) =>
        n.id !== id ? n : { ...n, data: { ...n.data, showExtraClusterConnectors: next } }
      )
    );
    setDirty(true);
    queueMicrotask(() => updateNodeInternals(id));
  }, [id, nodeData.showExtraClusterConnectors, nodes, setNodes, setDirty, updateNodeInternals]);

  const handleCopyConnectionDiagnostics = useCallback(() => {
    const self = nodes.find((n) => n.id === id);
    const touching = edges.filter((e) => e.source === id || e.target === id);
    const payload = {
      clusterId: id,
      label: nodeData.label,
      position: self?.position,
      measured:
        self && typeof self === "object" && "measured" in self
          ? (self as { measured?: { width?: number; height?: number } }).measured
          : undefined,
      edgesTouchingCluster: touching.map((e) => ({
        id: e.id,
        connectionType: (e.data as { connectionType?: string } | undefined)?.connectionType,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
      })),
      clusterPairEdges: touching.filter((e) => {
        const ct = (e.data as { connectionType?: string } | undefined)?.connectionType;
        return Boolean(ct && CLUSTER_EDGE_TYPES.has(ct));
      }),
    };
    const text = JSON.stringify(payload, null, 2);
    void navigator.clipboard
      .writeText(text)
      .then(() =>
        toast.success("Copied connection diagnostics", {
          description: "Paste into a note or issue.",
        })
      )
      .catch(() => toast.error("Could not copy to clipboard"));
  }, [id, nodeData.label, nodes, edges]);

  const openAddPoolDialog = useCallback(() => {
    if (pools.length === 0) return;
    setPoolDialog({ mode: "add" });
  }, [pools.length]);

  const openDuplicatePoolDialog = useCallback((duplicateSourceId: string) => {
    setPoolDialog({ mode: "duplicate", duplicateSourceId });
  }, []);

  const templatePoolForDialog = useMemo((): MinioServerPool => {
    const fallback: MinioServerPool = {
      id: "pool-1",
      nodeCount: 4,
      drivesPerNode: 2,
      diskSizeTb: 1,
      diskType: "ssd",
      ecParity: 3,
      ecParityUpgradePolicy: "upgrade",
      volumePath: "/data",
    };
    if (pools.length === 0) return fallback;
    if (poolDialog.mode === "duplicate") {
      return pools.find((p) => p.id === poolDialog.duplicateSourceId) ?? pools[pools.length - 1];
    }
    return pools[pools.length - 1];
  }, [poolDialog, pools]);

  const nextPoolId = `pool-${pools.length + 1}`;

  const handlePoolDialogConfirm = useCallback(
    async (newPool: MinioServerPool) => {
      const newNodes = nodes.map((n) =>
        n.id !== id ? n : { ...n, data: { ...n.data, serverPools: [...pools, newPool] } }
      );
      setNodes(newNodes);
      if (isRunning && activeDemoId) {
        await persistPoolChangeAndApply(newNodes);
      }
    },
    [pools, nodes, id, setNodes, isRunning, activeDemoId, persistPoolChangeAndApply]
  );

  const handleDuplicatePool = useCallback(
    (poolId: string) => {
      if (isRunning && activeDemoId) {
        openDuplicatePoolDialog(poolId);
        return;
      }
      const source = pools.find((p) => p.id === poolId);
      if (!source) return;
      const newPool = { ...source, id: `pool-${pools.length + 1}` };
      const newNodes = nodes.map((n) =>
        n.id !== id ? n : { ...n, data: { ...n.data, serverPools: [...pools, newPool] } }
      );
      setNodes(newNodes);
    },
    [pools, nodes, id, setNodes, isRunning, activeDemoId, openDuplicatePoolDialog]
  );

  const handleRemovePool = useCallback(
    (poolId: string) => {
      if (pools.length <= 1) return;
      if (isRunning) {
        const st = poolDecommissionStatus[poolId];
        if (st !== "decommissioned") {
          toast.error(
            st === "decommissioning"
              ? "Wait until decommission finishes (pool shows Decommissioned) before removing."
              : "Decommission and drain this pool first; remove is enabled only after status is Decommissioned."
          );
          return;
        }
      }
      const next = pools.filter((p) => p.id !== poolId);
      const plc = { ...(nodeData.poolLifecycle || {}) };
      delete plc[poolId];
      const newNodes = nodes.map((n) => {
        if (n.id !== id) return n;
        const data = { ...n.data, serverPools: next } as Record<string, unknown>;
        if (Object.keys(plc).length > 0) data.poolLifecycle = plc;
        else delete data.poolLifecycle;
        return { ...n, data };
      });
      setNodes(newNodes);
      setPoolDecommissionStatus((prev) => {
        const q = { ...prev };
        delete q[poolId];
        return q;
      });
      setPoolDecommissionDetail((prev) => {
        const q = { ...prev };
        delete q[poolId];
        return q;
      });
      if (isRunning && activeDemoId) {
        void persistPoolChangeAndApply(newNodes);
      }
    },
    [pools, nodes, id, setNodes, isRunning, activeDemoId, persistPoolChangeAndApply, poolDecommissionStatus, nodeData.poolLifecycle]
  );

  const handleStopNode = async (nodeId: string) => {
    if (!activeDemoId) return;
    toast.info(`Stopping ${nodeId}...`);
    try {
      await stopInstance(activeDemoId, nodeId);
      toast.success(`${nodeId} stopped`);
    } catch (err: any) {
      toast.error(`Failed to stop ${nodeId}`, { description: err.message });
    }
    setContextMenu(null);
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
    setContextMenu(null);
  };
  const handleStopDrive = async (nodeId: string, driveNum: number) => {
    if (!activeDemoId) return;
    toast.info(`Stopping drive ${driveNum} on ${nodeId}...`);
    try {
      await stopDrive(activeDemoId, nodeId, driveNum);
      toast.success(`Drive ${driveNum} stopped`);
    } catch (err: any) {
      toast.error(`Failed to stop drive`, { description: err.message });
    }
    setContextMenu(null);
    setDriveSubmenu(null);
  };
  const handleStartDrive = async (nodeId: string, driveNum: number) => {
    if (!activeDemoId) return;
    toast.info(`Restoring drive ${driveNum} on ${nodeId}...`);
    try {
      await startDrive(activeDemoId, nodeId, driveNum);
      toast.success(`Drive ${driveNum} restored`);
    } catch (err: any) {
      toast.error(`Failed to restore drive`, { description: err.message });
    }
    setContextMenu(null);
    setDriveSubmenu(null);
  };
  const handleResetCluster = async () => {
    if (!activeDemoId) return;
    setResetDialogOpen(false);
    setContextMenu(null);
    toast.info(`Removing all buckets from ${nodeData.label || id}...`);
    try {
      const res = await resetCluster(activeDemoId, id);
      toast.success(
        `Cluster reset: ${res.buckets_removed} bucket${res.buckets_removed !== 1 ? "s" : ""} removed`
      );
    } catch (err: any) {
      toast.error(`Failed to reset cluster`, { description: err.message });
    }
  };

  const handleDecommissionPool = async (poolId: string) => {
    if (!activeDemoId) return;
    try {
      await startPoolDecommission(activeDemoId, id, poolId);
      setPoolDecommissionStatus((prev) => ({ ...prev, [poolId]: "decommissioning" }));
      toast.success(`Pool ${poolId} decommission started`);
    } catch (e: any) {
      toast.error(`Failed to start decommission: ${e.message}`);
    }
  };

  const handleCancelDecommission = async (poolId: string) => {
    if (!activeDemoId) return;
    try {
      await cancelPoolDecommission(activeDemoId, id, poolId);
      setPoolDecommissionStatus((prev) => ({ ...prev, [poolId]: "active" }));
      toast.success(`Pool ${poolId} decommission cancelled`);
    } catch (e: any) {
      toast.error(`Failed to cancel decommission: ${e.message}`);
    }
  };

  // Hydrate from persisted demo YAML (pool_lifecycle)
  const pl = nodeData.poolLifecycle;
  useEffect(() => {
    if (!pl || typeof pl !== "object") return;
    setPoolDecommissionStatus((prev) => {
      const next = { ...prev };
      for (const [pid, st] of Object.entries(pl)) {
        if (st === "decommissioning") next[pid] = "decommissioning";
        else if (st === "decommissioned") next[pid] = "decommissioned";
        else if (st === "idle") next[pid] = "active";
      }
      return next;
    });
  }, [activeDemoId, id, JSON.stringify(pl)]);

  // On startup (when demo becomes running), poll each pool once to restore ephemeral decommission state
  useEffect(() => {
    if (!isRunning || !activeDemoId || pools.length === 0) return;
    pools.forEach(async (pool) => {
      try {
        const res = await getPoolDecommissionStatus(activeDemoId, id, pool.id);
        if (res.status && res.status !== "active") {
          setPoolDecommissionStatus((prev) => ({ ...prev, [pool.id]: res.status }));
        }
        if (res.detail) {
          setPoolDecommissionDetail((d) => ({ ...d, [pool.id]: res.detail! }));
        }
      } catch {
        // Pool may not have decommission in progress — ignore errors
      }
    });
  }, [isRunning, activeDemoId, id]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasDecommissioningPool = Object.values(poolDecommissionStatus).some((s) => s === "decommissioning");

  // While any pool is draining, poll mc status so the canvas shows live phase + enables remove when done
  useEffect(() => {
    if (!isRunning || !activeDemoId || pools.length === 0 || !hasDecommissioningPool) return;

    const tick = async () => {
      for (const pool of pools) {
        try {
          const res = await getPoolDecommissionStatus(activeDemoId!, id, pool.id);
          const mapped =
            res.status === "decommissioned"
              ? "decommissioned"
              : res.status === "decommissioning"
                ? "decommissioning"
                : "active";
          setPoolDecommissionStatus((prev) => {
            if (prev[pool.id] === mapped) return prev;
            return { ...prev, [pool.id]: mapped };
          });
          if (res.detail) {
            setPoolDecommissionDetail((d) => ({ ...d, [pool.id]: res.detail! }));
          }
        } catch {
          /* ignore */
        }
      }
    };

    const interval = setInterval(() => void tick(), 5000);
    void tick();
    return () => clearInterval(interval);
  }, [isRunning, activeDemoId, id, pools, hasDecommissioningPool]);

  return (
    <>
      <div
        ref={nodeRef}
        className="relative w-full rounded-xl p-3.5 cursor-pointer bg-zinc-100 dark:bg-zinc-900"
        style={{ border: "1.5px solid rgba(161,161,170,0.4)", minWidth: 380 }}
        onClick={() => {
          setSelectedNode(id);
          setSelectedClusterElement({ type: "cluster" });
          setContextMenu(null);
        }}
        onContextMenu={(e) => {
          if ((e.target as HTMLElement).closest("[data-node-icon]")) return;
          e.preventDefault();
          e.stopPropagation();
          setContextMenu({ type: "cluster", x: e.clientX, y: e.clientY });
        }}
      >
        <ClusterHeader
          label={nodeData.label || "MinIO Cluster"}
          pools={pools}
          aggregates={aggregates}
          clusterInstances={clusterInstances}
          clusterStatus={clusterStatus}
        />
        <FeatureBadges
          mcpEnabled={mcpEnabled}
          aistorTablesEnabled={aistorTablesEnabled}
          pools={pools}
          aggregates={aggregates}
        />

        {pools.map((pool, idx) => {
          const poolInstances = getPoolInstances(clusterInstances, id, idx + 1, pools.length);
          const flatOffset = pools.slice(0, idx).reduce((s, p) => s + p.nodeCount, 0);
          return (
            <PoolContainer
              key={pool.id}
              pool={pool}
              poolIndex={idx + 1}
              hidden={pools.length === 1}
              selected={selectedClusterElement?.type === "pool" && selectedClusterElement.poolId === pool.id}
              decommissionStatus={poolDecommissionStatus[pool.id]}
              decommissionDetail={poolDecommissionDetail[pool.id]}
              onPoolContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setContextMenu({ type: "pool", poolId: pool.id, x: e.clientX, y: e.clientY });
              }}
              onPoolClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setSelectedNode(id);
                setSelectedClusterElement({ type: "pool", poolId: pool.id });
              }}
            >
              {Array.from({ length: pool.nodeCount }, (_, ni) => {
                const nodeId = `${id}-pool${idx + 1}-node-${ni + 1}`;
                const inst = poolInstances.find((i) => i.node_id === nodeId);
                const flatIdx = flatOffset + ni;
                return (
                  <NodeTile
                    key={ni}
                    nodeIndex={ni + 1}
                    drivesPerNode={pool.drivesPerNode}
                    isRunning={isRunning}
                    instance={inst}
                    selected={
                      selectedClusterElement?.type === "node" &&
                      selectedClusterElement.poolId === pool.id &&
                      selectedClusterElement.nodeIndex === ni + 1
                    }
                    onNodeSelect={(e) => {
                      e.stopPropagation();
                      setSelectedNode(id);
                      setSelectedClusterElement({ type: "node", poolId: pool.id, nodeIndex: ni + 1 });
                    }}
                    onNodeContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setContextMenu({
                        type: "node",
                        nodeIdx: flatIdx,
                        x: e.nativeEvent.clientX,
                        y: e.nativeEvent.clientY,
                      });
                    }}
                    onDriveContextMenu={(_d, e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setContextMenu({
                        type: "node",
                        nodeIdx: flatIdx,
                        x: e.nativeEvent.clientX,
                        y: e.nativeEvent.clientY,
                      });
                      setDriveSubmenu(flatIdx);
                    }}
                  />
                );
              })}
            </PoolContainer>
          );
        })}

        {(isEditable || isRunning) && pools.length > 0 && (
          <AddPoolButton onClick={openAddPoolDialog} />
        )}
        {pools.length > 0 && <CapacityBar aggregates={aggregates} />}
        {/* Handles last so they stack above pool tiles / bars (avoids missed connection drops on dense cards). */}
        <Handle type="target" position={Position.Left} id="data-in" className="!z-20" />
        <Handle
          type="source"
          position={Position.Left}
          id="cluster-out-left"
          className="!z-20"
          style={{ top: "20%" }}
        />
        <Handle type="target" position={Position.Top} id="cluster-in-top" className="!z-20" />
        <Handle
          type="source"
          position={Position.Top}
          id="cluster-out"
          className="!z-20 !opacity-0 !w-4 !h-4 !min-w-[16px] !min-h-[16px] !border-0 !bg-transparent"
          style={{ position: "absolute", top: 0, left: "50%" }}
        />
        <Handle type="source" position={Position.Bottom} id="cluster-out-bottom" className="!z-20" />
        <Handle
          type="target"
          position={Position.Bottom}
          id="cluster-in"
          className="!z-20 !opacity-0 !w-4 !h-4 !min-w-[16px] !min-h-[16px] !border-0 !bg-transparent"
          style={{ position: "absolute", bottom: 0, left: "50%" }}
        />
        <Handle type="source" position={Position.Right} id="data-out" className="!z-20" />
        <Handle
          type="target"
          position={Position.Right}
          id="cluster-in-right"
          className="!z-20"
          style={{ top: "78%" }}
        />
        {nodeData.showExtraClusterConnectors ? (
          <>
            <Handle
              type="source"
              position={Position.Top}
              id="cluster-aux-out-tl"
              className="!z-20 !h-3 !w-3"
              style={{ left: "18%", top: 0 }}
            />
            <Handle
              type="target"
              position={Position.Bottom}
              id="cluster-aux-in-br"
              className="!z-20 !h-3 !w-3"
              style={{ left: "82%", bottom: 0 }}
            />
          </>
        ) : null}
      </div>

      {contextMenu && (
        <ClusterContextMenu
          {...contextMenu}
          clusterId={id}
          clusterData={nodeData}
          isRunning={isRunning}
          demoId={activeDemoId}
          instances={clusterInstances}
          consoleUrl={consoleUrl}
          driveSubmenu={driveSubmenu}
          onSetDriveSubmenu={setDriveSubmenu}
          onClose={() => {
            setContextMenu(null);
            setDriveSubmenu(null);
          }}
          onOpenAdmin={(tab) => {
            setAdminDefaultTab(tab);
            setAdminPanelOpen(true);
            setContextMenu(null);
          }}
          onOpenMcp={(tab) => {
            setMcpDefaultTab(tab);
            setMcpPanelOpen(true);
            setContextMenu(null);
          }}
          onStopNode={handleStopNode}
          onStartNode={handleStartNode}
          onStopDrive={handleStopDrive}
          onStartDrive={handleStartDrive}
          onResetCluster={handleResetCluster}
          onRequestResetCluster={() => {
            setResetDialogOpen(true);
            setContextMenu(null);
            setDriveSubmenu(null);
          }}
          onCopy={() => {
            const self = nodes.find((n) => n.id === id);
            if (self) setClipboard(self);
          }}
          onDeleteCluster={() => {
            openEditorDeleteDialog({ type: "node", ids: [id] });
            setContextMenu(null);
            setDriveSubmenu(null);
          }}
          onViewInstances={() => {
            setActiveView("control-plane");
            setContextMenu(null);
          }}
          onEditCluster={() => {
            setSelectedNode(id);
            setSelectedClusterElement({ type: "cluster" });
            setContextMenu(null);
          }}
          onAddPool={() => {
            openAddPoolDialog();
            setContextMenu(null);
          }}
          onEditPool={(poolId) => {
            setSelectedNode(id);
            setSelectedClusterElement({ type: "pool", poolId });
            setContextMenu(null);
          }}
          onDuplicatePool={(poolId) => {
            handleDuplicatePool(poolId);
            setContextMenu(null);
          }}
          onRequestRemovePool={(poolId) => {
            setRemovePoolTarget(poolId);
            setContextMenu(null);
            setDriveSubmenu(null);
          }}
          onViewNodeDetails={(poolId, nodeIndex) => {
            setSelectedNode(id);
            setSelectedClusterElement({ type: "node", poolId, nodeIndex });
            setContextMenu(null);
          }}
          onViewLogs={(nodeId) => setLogViewerNodeId(nodeId)}
          onDecommissionPool={handleDecommissionPool}
          onCancelDecommission={handleCancelDecommission}
          poolDecommissionStatus={poolDecommissionStatus}
          poolsCount={pools.length}
          showExtraClusterConnectors={nodeData.showExtraClusterConnectors === true}
          onReanchorClusterConnections={() => reanchorClusterEdges(id)}
          onReanchorAllClusterConnections={() => reanchorAllClusterToClusterEdges()}
          onToggleExtraClusterConnectors={handleToggleExtraClusterConnectors}
          onCopyConnectionDiagnostics={handleCopyConnectionDiagnostics}
        />
      )}

      <AlertDialog open={resetDialogOpen} onOpenChange={(open) => !open && setResetDialogOpen(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset cluster?</AlertDialogTitle>
            <AlertDialogDescription>
              Remove all buckets from this cluster{nodeData.label ? ` (${nodeData.label})` : ""}. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleResetCluster()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Reset cluster
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={removePoolTarget !== null} onOpenChange={(open) => !open && setRemovePoolTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove pool?</AlertDialogTitle>
            <AlertDialogDescription>
              {isRunning
                ? "Remove this pool from the diagram and update Docker? This cannot be undone."
                : "Remove this pool from the cluster configuration? This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (removePoolTarget) handleRemovePool(removePoolTarget);
                setRemovePoolTarget(null);
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Remove pool
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AddPoolDialog
        open={poolDialog.mode !== "closed"}
        onOpenChange={(o) => {
          if (!o) setPoolDialog({ mode: "closed" });
        }}
        templatePool={templatePoolForDialog}
        nextPoolId={nextPoolId}
        isRunning={isRunning}
        title={poolDialog.mode === "duplicate" ? "Duplicate server pool" : "Add server pool"}
        onConfirm={handlePoolDialogConfirm}
      />

      <MinioAdminPanel
        open={adminPanelOpen}
        onOpenChange={setAdminPanelOpen}
        clusterId={id}
        clusterLabel={nodeData.label || "MinIO Cluster"}
        defaultTab={adminDefaultTab}
        consoleUrl={consoleUrl ?? undefined}
        nodes={clusterInstances.map((inst) => ({
          id: inst.node_id,
          label: inst.node_id.replace(`${id}-`, ""),
        }))}
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

      {logViewerNodeId && activeDemoId && (
        <LogViewer
          demoId={activeDemoId}
          nodeId={logViewerNodeId}
          componentId="minio"
          onClose={() => setLogViewerNodeId(null)}
        />
      )}
    </>
  );
}
