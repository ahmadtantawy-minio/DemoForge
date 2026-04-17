import type { Edge, Node } from "@xyflow/react";
import type { SelectedClusterElement } from "../../stores/diagramStore";
import type { ContainerInstance, MinioServerPool } from "../../types";
import ClusterPropertiesPanel from "./cluster/ClusterPropertiesPanel";
import PoolPropertiesPanel from "./cluster/PoolPropertiesPanel";
import NodePropertiesPanel from "./cluster/NodePropertiesPanel";
import { migrateClusterData } from "../../lib/clusterMigration";
import { clusterDataPatchAffectsCompose } from "../../lib/persistClusterTopology";

interface ClusterPropertiesRouterProps {
  selectedNodeId: string;
  selectedNode: Node;
  selectedClusterElement: SelectedClusterElement | null;
  nodes: Node[];
  edges: Edge[];
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  instances: ContainerInstance[];
  demos: { id: string; status?: string }[];
  activeDemoId: string | null;
  scheduleClusterTopoApply: () => void;
}

export function ClusterPropertiesRouter({
  selectedNodeId,
  selectedNode,
  selectedClusterElement,
  nodes,
  edges,
  setNodes,
  setEdges,
  instances,
  demos,
  activeDemoId,
  scheduleClusterTopoApply,
}: ClusterPropertiesRouterProps) {
  const cData = migrateClusterData(selectedNode.data as Record<string, unknown>);
  const pools = cData.serverPools || [];
  const isRunning = demos.find((d) => d.id === activeDemoId)?.status === "running";
  const updateCluster = (patch: Record<string, unknown>) => {
    setNodes(nodes.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n)));
    if (isRunning && clusterDataPatchAffectsCompose(patch)) scheduleClusterTopoApply();
  };
  const updatePool = (poolId: string, patch: Partial<MinioServerPool>) => {
    const newPools = pools.map((p) => (p.id === poolId ? { ...p, ...patch } : p));
    updateCluster({ serverPools: newPools });
  };

  const element = selectedClusterElement;

  if (!element || element.type === "cluster") {
    return (
      <ClusterPropertiesPanel
        nodeId={selectedNodeId}
        data={cData}
        nodes={nodes}
        edges={edges}
        instances={instances}
        onUpdate={updateCluster}
        setEdges={setEdges}
      />
    );
  }

  if (element.type === "pool") {
    const poolIdx = pools.findIndex((p) => p.id === element.poolId);
    const pool = pools[poolIdx];
    if (!pool) {
      return (
        <ClusterPropertiesPanel
          nodeId={selectedNodeId}
          data={cData}
          nodes={nodes}
          edges={edges}
          instances={instances}
          onUpdate={updateCluster}
          setEdges={setEdges}
        />
      );
    }
    return (
      <PoolPropertiesPanel
        pool={pool}
        poolIndex={poolIdx + 1}
        totalPools={pools.length}
        onUpdate={(patch) => updatePool(pool.id, patch)}
      />
    );
  }

  if (element.type === "node") {
    const poolIdx = pools.findIndex((p) => p.id === element.poolId);
    const pool = pools[poolIdx] || pools[0];
    const containerName =
      pools.length === 1
        ? `${selectedNodeId}-node-${element.nodeIndex}`
        : `${selectedNodeId}-pool${poolIdx + 1}-node-${element.nodeIndex}`;
    const inst = instances.find((i) => i.node_id === containerName);
    return (
      <NodePropertiesPanel
        nodeId={containerName}
        poolId={element.poolId}
        nodeIndex={element.nodeIndex}
        instance={inst}
        drivesPerNode={pool?.drivesPerNode ?? 4}
        isRunning={!!isRunning}
      />
    );
  }

  return (
    <ClusterPropertiesPanel
      nodeId={selectedNodeId}
      data={cData}
      nodes={nodes}
      edges={edges}
      instances={instances}
      onUpdate={updateCluster}
      setEdges={setEdges}
    />
  );
}
