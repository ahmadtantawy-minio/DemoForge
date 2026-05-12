import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import { fetchComponents } from "../../api/client";
import type { ComponentNodeData, ComponentSummary } from "../../types";
import SqlPlaybookPanel from "./SqlPlaybookPanel";
import {
  saveDiagramAndApplyClusterTopology,
} from "../../lib/persistClusterTopology";
import { getEventProcessorConnectionRouting } from "./eventProcessorRouting";
import { EdgePropertiesPanel } from "./EdgePropertiesPanel";
import { GroupPropertiesPanel } from "./GroupPropertiesPanel";
import { AnnotationPropertiesPanel } from "./AnnotationPropertiesPanel";
import { ClusterPropertiesRouter } from "./ClusterPropertiesRouter";
import { StickyNotePropertiesPanel } from "./StickyNotePropertiesPanel";
import { CanvasImagePropertiesPanel } from "./CanvasImagePropertiesPanel";
import { ComponentNodePropertiesPanel } from "./ComponentNodePropertiesPanel";

export default function PropertiesPanel() {
  const {
    selectedNodeId,
    selectedEdgeId,
    nodes,
    edges,
    setNodes: _setNodes,
    setEdges,
    componentManifests,
    setDirty,
    selectedClusterElement,
    setDesignerWebUiOverlay,
  } = useDiagramStore();
  const setNodes = (ns: typeof nodes) => {
    _setNodes(ns);
    setDirty(true);
  };
  const { instances, activeDemoId, demos } = useDemoStore();
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [sqlEditorOpen, setSqlEditorOpen] = useState(false);
  const [sqlEditorScenarioId, setSqlEditorScenarioId] = useState("ecommerce-orders");
  const clusterTopoApplyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (clusterTopoApplyTimerRef.current) clearTimeout(clusterTopoApplyTimerRef.current);
    },
    []
  );

  useEffect(() => {
    if (clusterTopoApplyTimerRef.current) {
      clearTimeout(clusterTopoApplyTimerRef.current);
      clusterTopoApplyTimerRef.current = null;
    }
  }, [selectedNodeId]);

  const scheduleClusterTopoApply = useCallback(() => {
    if (!activeDemoId || !selectedNodeId) return;
    const running = demos.find((d) => d.id === activeDemoId)?.status === "running";
    if (!running) return;
    if (clusterTopoApplyTimerRef.current) clearTimeout(clusterTopoApplyTimerRef.current);
    clusterTopoApplyTimerRef.current = setTimeout(() => {
      clusterTopoApplyTimerRef.current = null;
      const st = useDiagramStore.getState();
      const sid = st.selectedNodeId;
      if (!sid || sid !== selectedNodeId) return;
      const n = st.nodes.find((x) => x.id === sid);
      if (!n || n.type !== "cluster") return;
      void saveDiagramAndApplyClusterTopology(activeDemoId, sid, st.nodes, st.edges);
    }, 650);
  }, [activeDemoId, selectedNodeId, demos]);

  useEffect(() => {
    fetchComponents()
      .then((res) => setComponents(res.components))
      .catch(() => {});
  }, []);

  const eventProcessorRouting = useMemo(() => {
    if (!selectedNodeId) return null;
    const n = nodes.find((x) => x.id === selectedNodeId);
    const cid = (n?.data as ComponentNodeData | undefined)?.componentId;
    if (cid !== "event-processor") return null;
    return getEventProcessorConnectionRouting(selectedNodeId, edges);
  }, [selectedNodeId, nodes, edges]);

  if (selectedEdgeId && !selectedNodeId) {
    return (
      <EdgePropertiesPanel
        selectedEdgeId={selectedEdgeId}
        edges={edges}
        nodes={nodes}
        setEdges={setEdges}
        componentManifests={componentManifests}
      />
    );
  }

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  if (!selectedNode) {
    const activeDemo = demos.find((d) => d.id === activeDemoId);
    const isRunning = activeDemo?.status === "running";
    const hasDataGen = nodes.some((n) => (n.data as { componentId?: string })?.componentId === "data-generator");
    const hasTrino = nodes.some((n) => (n.data as { componentId?: string })?.componentId === "trino");
    if (isRunning && hasDataGen && hasTrino && activeDemoId) {
      return (
        <div className="w-full h-full bg-card border-l border-border overflow-y-auto">
          <SqlPlaybookPanel demoId={activeDemoId} />
        </div>
      );
    }
    return (
      <div className="w-full h-full bg-card border-l border-border p-3 flex items-center justify-center">
        <p className="text-xs text-muted-foreground">Select a node or edge to view properties</p>
      </div>
    );
  }

  if (selectedNode.type === "group") {
    return (
      <GroupPropertiesPanel
        selectedNodeId={selectedNodeId!}
        selectedNode={selectedNode}
        nodes={nodes}
        setNodes={setNodes}
      />
    );
  }

  if (selectedNode.type === "annotation") {
    return (
      <AnnotationPropertiesPanel
        selectedNodeId={selectedNodeId!}
        selectedNode={selectedNode}
        nodes={nodes}
        setNodes={setNodes}
      />
    );
  }

  if (selectedNode.type === "cluster") {
    return (
      <ClusterPropertiesRouter
        selectedNodeId={selectedNodeId!}
        selectedNode={selectedNode}
        selectedClusterElement={selectedClusterElement}
        nodes={nodes}
        edges={edges}
        setNodes={setNodes}
        setEdges={setEdges}
        instances={instances}
        demos={demos}
        activeDemoId={activeDemoId}
        scheduleClusterTopoApply={scheduleClusterTopoApply}
      />
    );
  }

  if (selectedNode.type === "sticky") {
    return (
      <StickyNotePropertiesPanel
        selectedNodeId={selectedNodeId!}
        selectedNode={selectedNode}
        nodes={nodes}
        setNodes={setNodes}
      />
    );
  }

  if (selectedNode.type === "canvas-image") {
    return (
      <CanvasImagePropertiesPanel
        selectedNodeId={selectedNodeId!}
        selectedNode={selectedNode}
        nodes={nodes}
        edges={edges}
        setNodes={setNodes}
        replaceNodesRaw={_setNodes}
        setDirty={setDirty}
        activeDemoId={activeDemoId}
      />
    );
  }

  const data = selectedNode.data as unknown as ComponentNodeData;
  const instance = instances.find((i) => i.node_id === selectedNodeId);
  const componentDef = components.find((c) => c.id === data.componentId);
  const variants = componentDef?.variants ?? [];
  const activeDemo = demos.find((d) => d.id === activeDemoId);
  const isExperience = activeDemo?.mode === "experience";
  const isRunning = activeDemo?.status === "running";

  const updateData = (patch: Partial<ComponentNodeData>) => {
    setNodes(
      nodes.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n))
    );
  };

  const updateConfig = (key: string, value: string) => {
    updateData({ config: { ...data.config, [key]: value } });
  };

  return (
    <ComponentNodePropertiesPanel
      selectedNodeId={selectedNodeId!}
      data={data}
      instance={instance}
      componentDef={componentDef}
      variants={variants}
      activeDemoId={activeDemoId}
      isExperience={!!isExperience}
      isRunning={!!isRunning}
      nodes={nodes}
      edges={edges}
      setEdges={setEdges}
      eventProcessorRouting={eventProcessorRouting}
      updateData={updateData}
      updateConfig={updateConfig}
      sqlEditorOpen={sqlEditorOpen}
      setSqlEditorOpen={setSqlEditorOpen}
      sqlEditorScenarioId={sqlEditorScenarioId}
      setSqlEditorScenarioId={setSqlEditorScenarioId}
      setDesignerWebUiOverlay={setDesignerWebUiOverlay}
    />
  );
}
