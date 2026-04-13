import { useState, useCallback, useEffect, useRef } from "react";
import { Handle, Position, type NodeProps, useUpdateNodeInternals } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { stopInstance, startInstance, resetCluster, stopDrive, startDrive, startPoolDecommission, cancelPoolDecommission, getPoolDecommissionStatus } from "../../../api/client";
import { toast } from "../../../lib/toast";
import { migrateClusterData } from "../../../lib/clusterMigration";
import { getClusterInstances, getPoolInstances, computeClusterAggregates } from "../../../lib/clusterUtils";
import ClusterHeader from "./cluster/ClusterHeader";
import FeatureBadges from "./cluster/FeatureBadges";
import PoolContainer from "./cluster/PoolContainer";
import NodeTile from "./cluster/NodeTile";
import CapacityBar from "./cluster/CapacityBar";
import AddPoolButton from "./cluster/AddPoolButton";
import ClusterContextMenu from "./cluster/ClusterContextMenu";
import MinioAdminPanel from "../../minio/MinioAdminPanel";
import McpPanel from "../../minio/McpPanel";
import LogViewer from "../../logs/LogViewer";

export default function ClusterNode({ id, data }: NodeProps) {
  const nodeRef = useRef<HTMLDivElement>(null);
  const updateNodeInternals = useUpdateNodeInternals();
  const nodeData = migrateClusterData(data);
  const pools = nodeData.serverPools || [];
  const { setSelectedNode, setSelectedClusterElement, selectedClusterElement, nodes, setNodes, setClipboard } = useDiagramStore();
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

  const _apiBase = (import.meta as any).env?.VITE_API_URL || "http://localhost:9210";
  const _lbInst = instances.find((i) => i.node_id === `${id}-lb`);
  const consoleUrl =
    _lbInst?.health === "healthy" && activeDemoId
      ? `${_apiBase}/proxy/${activeDemoId}/${id}-lb/console/`
      : null;

  const [contextMenu, setContextMenu] = useState<{
    type: "cluster" | "node" | "pool";
    nodeIdx?: number;
    poolId?: string;
    x: number;
    y: number;
  } | null>(null);
  const [driveSubmenu, setDriveSubmenu] = useState<number | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRemovePool, setConfirmRemovePool] = useState(false);
  const [adminPanelOpen, setAdminPanelOpen] = useState(false);
  const [adminDefaultTab, setAdminDefaultTab] = useState<"overview" | "logs">("overview");
  const [mcpPanelOpen, setMcpPanelOpen] = useState(false);
  const [mcpDefaultTab, setMcpDefaultTab] = useState<"mcp-tools" | "ai-chat">("mcp-tools");
  const [logViewerNodeId, setLogViewerNodeId] = useState<string | null>(null);
  const [poolDecommissionStatus, setPoolDecommissionStatus] = useState<Record<string, "active" | "decommissioning" | "decommissioned">>({});

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

  const handleAddPool = useCallback(() => {
    if (pools.length === 0) return;
    const lastPool = pools[pools.length - 1];
    const newPool = { ...lastPool, id: `pool-${pools.length + 1}` };
    setNodes(
      nodes.map((n) =>
        n.id !== id ? n : { ...n, data: { ...n.data, serverPools: [...pools, newPool] } }
      )
    );
  }, [pools, nodes, id, setNodes]);

  const handleDuplicatePool = useCallback(
    (poolId: string) => {
      const source = pools.find((p) => p.id === poolId);
      if (!source) return;
      const newPool = { ...source, id: `pool-${pools.length + 1}` };
      setNodes(
        nodes.map((n) =>
          n.id !== id ? n : { ...n, data: { ...n.data, serverPools: [...pools, newPool] } }
        )
      );
    },
    [pools, nodes, id, setNodes]
  );

  const handleRemovePool = useCallback(
    (poolId: string) => {
      if (pools.length <= 1) return;
      const next = pools.filter((p) => p.id !== poolId);
      setNodes(
        nodes.map((n) =>
          n.id !== id ? n : { ...n, data: { ...n.data, serverPools: next } }
        )
      );
    },
    [pools, nodes, id, setNodes]
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
    setConfirmReset(false);
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

  // On startup (when demo becomes running), poll each pool once to restore ephemeral decommission state
  useEffect(() => {
    if (!isRunning || !activeDemoId || pools.length === 0) return;
    pools.forEach(async (pool) => {
      try {
        const res = await getPoolDecommissionStatus(activeDemoId, id, pool.id);
        if (res.status && res.status !== "active") {
          setPoolDecommissionStatus(prev => ({ ...prev, [pool.id]: res.status }));
        }
      } catch {
        // Pool may not have decommission in progress — ignore errors
      }
    });
  }, [isRunning, activeDemoId, id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div
        ref={nodeRef}
        className="w-full rounded-xl p-3.5 cursor-pointer bg-zinc-100 dark:bg-zinc-900"
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
        <Handle type="target" position={Position.Left} id="data-in" />
        <Handle type="target" position={Position.Top} id="cluster-in-top" />
        <Handle type="source" position={Position.Top} id="cluster-out" className="!opacity-0 !w-0 !h-0 !min-w-0 !min-h-0" style={{ position: "absolute", top: 0, left: "50%" }} />
        <Handle type="source" position={Position.Bottom} id="cluster-out-bottom" />
        <Handle type="target" position={Position.Bottom} id="cluster-in" className="!opacity-0 !w-0 !h-0 !min-w-0 !min-h-0" style={{ position: "absolute", bottom: 0, left: "50%" }} />

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

        {isEditable && pools.length > 0 && <AddPoolButton onClick={handleAddPool} />}
        {pools.length > 0 && <CapacityBar aggregates={aggregates} />}
        <Handle type="source" position={Position.Right} id="data-out" />
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
          onCopy={() => {
            const self = nodes.find((n) => n.id === id);
            if (self) setClipboard(self);
          }}
          onDeleteCluster={() => {
            setNodes(nodes.filter((n) => n.id !== id));
            setContextMenu(null);
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
            handleAddPool();
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
          onRemovePool={(poolId) => {
            handleRemovePool(poolId);
            setConfirmRemovePool(false);
            setContextMenu(null);
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
          confirmReset={confirmReset}
          onSetConfirmReset={setConfirmReset}
          confirmDelete={confirmDelete}
          onSetConfirmDelete={setConfirmDelete}
          confirmRemovePool={confirmRemovePool}
          onSetConfirmRemovePool={setConfirmRemovePool}
        />
      )}

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
