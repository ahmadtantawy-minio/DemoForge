import { useState, useCallback, useEffect, useRef } from "react";
import { Handle, Position, type NodeProps, NodeResizer, useReactFlow } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { stopInstance, startInstance, resetCluster, stopDrive, startDrive } from "../../../api/client";
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

export default function ClusterNode({ id, data, selected }: NodeProps) {
  const nodeRef = useRef<HTMLDivElement>(null);
  const [minSize, setMinSize] = useState<{ width: number; height: number }>({ width: 380, height: 160 });
  const { updateNode } = useReactFlow();
  const nodeData = migrateClusterData(data);
  const pools = nodeData.serverPools || [];
  const { setSelectedNode, setSelectedClusterElement, selectedClusterElement, nodes, setNodes } = useDiagramStore();
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

  useEffect(() => {
    const el = nodeRef.current;
    if (!el) return;
    const measure = () => {
      // offsetHeight/offsetWidth include border+padding and reflect the actual rendered size
      const h = el.offsetHeight;
      const w = el.offsetWidth;
      if (h > 0) {
        updateNode(id, { height: h, width: Math.max(w, 380) });
        setMinSize({ width: Math.max(w, 380), height: h });
      }
    };
    const rafId = requestAnimationFrame(measure);
    // Re-measure after async data (instances, clusterHealth) may have loaded
    const timerId = setTimeout(measure, 400);
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => {
      cancelAnimationFrame(rafId);
      clearTimeout(timerId);
      observer.disconnect();
    };
  }, [id, updateNode]);

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

  return (
    <>
      <NodeResizer isVisible={selected} minWidth={minSize.width} minHeight={minSize.height} />
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
        <Handle
          type="target"
          position={Position.Top}
          id="data-in-top"
          className="!left-1/3 !w-0 !h-0 !border-0 !bg-transparent !min-w-0 !min-h-0"
        />
        <Handle
          type="source"
          position={Position.Top}
          id="cluster-out"
          style={{ width: 12, height: 12, background: "#3b82f6", border: "2px solid #60a5fa", zIndex: 10 }}
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
        />
        <Handle
          type="source"
          position={Position.Bottom}
          id="cluster-out-bottom"
          style={{ width: 12, height: 12, background: "#3b82f6", border: "2px solid #60a5fa", zIndex: 10, opacity: 0 }}
        />

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
                const nodeId =
                  pools.length === 1
                    ? `${id}-node-${ni + 1}`
                    : `${id}-pool${idx + 1}-node-${ni + 1}`;
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
    </>
  );
}
