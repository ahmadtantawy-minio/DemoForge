import { useEffect, useState } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import HealthBadge from "../control-plane/HealthBadge";
import { proxyUrl, fetchComponents } from "../../api/client";
import type { ComponentNodeData, ComponentSummary, ComponentEdgeData, ConnectionType, ConnectionConfigField } from "../../types";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import ConfigSchemaForm from "./ConfigSchemaForm";

const connectionColors: Record<string, string> = {
  s3: "#3b82f6",
  http: "#6b7280",
  metrics: "#22c55e",
  replication: "#a855f7",
  "site-replication": "#d946ef",
  "load-balance": "#f97316",
  data: "#6b7280",
  "metrics-query": "#22c55e",
  tiering: "#eab308",
  "file-push": "#06b6d4",
};

const connectionLabels: Record<string, string> = {
  s3: "S3",
  http: "HTTP",
  metrics: "Metrics",
  replication: "Replication",
  "site-replication": "Site Replication",
  "load-balance": "Load Balance",
  data: "Data",
  "metrics-query": "PromQL",
  tiering: "Tiering",
  "file-push": "File Push",
};

export default function PropertiesPanel() {
  const { selectedNodeId, selectedEdgeId, nodes, edges, setNodes, setEdges, componentManifests } = useDiagramStore();
  const { instances } = useDemoStore();
  const [components, setComponents] = useState<ComponentSummary[]>([]);

  useEffect(() => {
    fetchComponents()
      .then((res) => setComponents(res.components))
      .catch(() => {});
  }, []);

  // --- Edge properties view ---
  if (selectedEdgeId && !selectedNodeId) {
    const selectedEdge = edges.find((e) => e.id === selectedEdgeId);
    if (!selectedEdge) {
      return (
        <div className="w-full h-full bg-card border-l border-border p-3 flex items-center justify-center">
          <p className="text-xs text-muted-foreground">Edge not found</p>
        </div>
      );
    }

    const edgeData = (selectedEdge.data ?? {}) as unknown as ComponentEdgeData;
    const connType = edgeData.connectionType ?? "data";
    const color = connectionColors[connType] ?? "#6b7280";
    const label = connectionLabels[connType] ?? connType;

    const sourceNode = nodes.find((n) => n.id === selectedEdge.source);
    const targetNode = nodes.find((n) => n.id === selectedEdge.target);

    // Get config schema fields for this connection type
    const sourceComponentId = (sourceNode?.data as any)?.componentId;
    const targetComponentId = (targetNode?.data as any)?.componentId;
    const sourceConns = sourceComponentId ? componentManifests[sourceComponentId] : null;
    const targetConns = targetComponentId ? componentManifests[targetComponentId] : null;

    const configFieldMap = new Map<string, ConnectionConfigField>();
    if (sourceConns) {
      const provides = sourceConns.provides.find((p) => p.type === connType);
      if (provides?.config_schema) {
        for (const f of provides.config_schema) configFieldMap.set(f.key, f);
      }
    }
    if (targetConns) {
      const accepts = targetConns.accepts.find((a) => a.type === connType);
      if (accepts?.config_schema) {
        // accepts side takes precedence on duplicate keys
        for (const f of accepts.config_schema) configFieldMap.set(f.key, f);
      }
    }
    const configFields = Array.from(configFieldMap.values());

    const updateEdgeData = (patch: Partial<ComponentEdgeData>) => {
      setEdges(
        edges.map((e) =>
          e.id === selectedEdgeId ? { ...e, data: { ...e.data, ...patch } } : e
        )
      );
    };

    return (
      <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Connection Properties
        </div>

        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-1">Type</div>
          <div className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-full shrink-0"
              style={{ backgroundColor: color }}
            />
            <span className="text-sm font-medium text-foreground">{label}</span>
          </div>
        </div>

        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-1">Direction</div>
          <div className="text-sm text-foreground">
            {(sourceNode?.data as any)?.label ?? selectedEdge.source}
            <span className="text-muted-foreground mx-1">&rarr;</span>
            {(targetNode?.data as any)?.label ?? selectedEdge.target}
          </div>
        </div>

        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Label</label>
          <Input
            type="text"
            value={edgeData.label ?? ""}
            onChange={(e) => updateEdgeData({ label: e.target.value })}
            placeholder="Optional label"
            className="h-8 text-sm"
          />
        </div>

        <div className="mb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={edgeData.autoConfigure ?? true}
              onChange={(e) => updateEdgeData({ autoConfigure: e.target.checked })}
              className="rounded border-border"
            />
            <span className="text-xs text-foreground">Auto-configure</span>
          </label>
          <p className="text-[10px] text-muted-foreground mt-0.5 ml-5">
            Automatically configure connection environment variables on deploy
          </p>
        </div>

        {configFields.length > 0 && (
          <div className="mb-3 pt-2 border-t border-border">
            <div className="text-xs text-muted-foreground mb-2">Configuration</div>
            <ConfigSchemaForm
              fields={configFields}
              values={edgeData.connectionConfig ?? {}}
              onChange={(key, value) =>
                updateEdgeData({
                  connectionConfig: { ...(edgeData.connectionConfig ?? {}), [key]: value },
                })
              }
            />
          </div>
        )}
      </div>
    );
  }

  // --- Node properties view ---
  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  if (!selectedNode) {
    return (
      <div className="w-full h-full bg-card border-l border-border p-3 flex items-center justify-center">
        <p className="text-xs text-muted-foreground">Select a node or edge to view properties</p>
      </div>
    );
  }

  // --- Group properties ---
  if (selectedNode.type === "group") {
    const gData = selectedNode.data as any;
    const updateGroup = (patch: Record<string, any>) => {
      setNodes(nodes.map((n) => n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n));
    };
    return (
      <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Group</div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Label</label>
          <Input type="text" value={gData.label ?? ""} onChange={(e) => updateGroup({ label: e.target.value })} className="h-8 text-sm" />
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Description</label>
          <textarea
            value={gData.description ?? ""}
            onChange={(e) => updateGroup({ description: e.target.value })}
            className="w-full bg-background border border-input rounded-md px-3 py-2 text-sm min-h-[60px] resize-y focus:outline-none focus:ring-1 focus:ring-ring"
            placeholder="Describe this group..."
          />
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Color</label>
          <div className="flex gap-2">
            {["#3b82f6", "#22c55e", "#eab308", "#ef4444", "#a855f7", "#f97316", "#06b6d4", "#6b7280"].map((c) => (
              <button
                key={c}
                className={`w-6 h-6 rounded-full border-2 transition-all ${gData.color === c ? "border-foreground scale-110" : "border-transparent"}`}
                style={{ background: c }}
                onClick={() => updateGroup({ color: c })}
              />
            ))}
          </div>
        </div>
        <div className="mb-3 pt-2 border-t border-border">
          <label className="text-xs text-muted-foreground block mb-1">Mode</label>
          <Select value={gData.mode || "visual"} onValueChange={(v) => updateGroup({ mode: v })}>
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="visual">Visual (grouping only)</SelectItem>
              <SelectItem value="cluster">Cluster (coordinated deployment)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {(gData.mode === "cluster") && (
          <>
            <div className="mb-3">
              <label className="text-xs text-muted-foreground block mb-1">Drives per Node</label>
              <Input
                type="number"
                value={gData.cluster_config?.drives_per_node ?? 1}
                onChange={(e) => updateGroup({ cluster_config: { ...(gData.cluster_config || {}), drives_per_node: parseInt(e.target.value) || 1 } })}
                className="h-8 text-sm"
                min={1}
                max={4}
              />
            </div>
            <div className="mb-3">
              <label className="text-xs text-muted-foreground block mb-1">Root User</label>
              <Input
                type="text"
                value={gData.cluster_config?.root_user ?? "minioadmin"}
                onChange={(e) => updateGroup({ cluster_config: { ...(gData.cluster_config || {}), root_user: e.target.value } })}
                className="h-8 text-sm"
              />
            </div>
            <div className="mb-3">
              <label className="text-xs text-muted-foreground block mb-1">Root Password</label>
              <Input
                type="text"
                value={gData.cluster_config?.root_password ?? "minioadmin"}
                onChange={(e) => updateGroup({ cluster_config: { ...(gData.cluster_config || {}), root_password: e.target.value } })}
                className="h-8 text-sm"
              />
            </div>
          </>
        )}
      </div>
    );
  }

  // --- Sticky note properties ---
  if (selectedNode.type === "sticky") {
    const sData = selectedNode.data as any;
    const updateSticky = (patch: Record<string, any>) => {
      setNodes(nodes.map((n) => n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n));
    };
    return (
      <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Note</div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Text</label>
          <textarea
            value={sData.text ?? ""}
            onChange={(e) => updateSticky({ text: e.target.value })}
            className="w-full bg-background border border-input rounded-md px-3 py-2 text-sm min-h-[120px] resize-y focus:outline-none focus:ring-1 focus:ring-ring font-mono"
            placeholder="Add your notes here..."
          />
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Color</label>
          <div className="flex gap-2">
            {["#eab308", "#22c55e", "#3b82f6", "#ef4444", "#a855f7", "#f97316"].map((c) => (
              <button
                key={c}
                className={`w-6 h-6 rounded-full border-2 transition-all ${sData.color === c ? "border-foreground scale-110" : "border-transparent"}`}
                style={{ background: c }}
                onClick={() => updateSticky({ color: c })}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // --- Component node properties ---
  const data = selectedNode.data as unknown as ComponentNodeData;
  const instance = instances.find((i) => i.node_id === selectedNodeId);
  const componentDef = components.find((c) => c.id === data.componentId);
  const variants = componentDef?.variants ?? [];

  const updateData = (patch: Partial<ComponentNodeData>) => {
    setNodes(
      nodes.map((n) =>
        n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n
      )
    );
  };

  const updateConfig = (key: string, value: string) => {
    updateData({ config: { ...data.config, [key]: value } });
  };

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Properties
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Display Name</label>
        <Input
          type="text"
          value={data.displayName ?? ""}
          onChange={(e) => updateData({ displayName: e.target.value })}
          placeholder={data.label || data.componentId}
          className="h-8 text-sm"
        />
      </div>

      <div className="mb-3">
        <div className="text-xs text-muted-foreground mb-1">Component</div>
        <div className="text-sm font-medium text-foreground">{data.label}</div>
        <div className="text-xs text-muted-foreground">{data.componentId}</div>
        {componentDef?.image && (
          <div className="text-xs text-muted-foreground mt-1 font-mono bg-muted px-1.5 py-0.5 rounded inline-block">
            {componentDef.image}
          </div>
        )}
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Variant</label>
        {variants.length > 0 ? (
          <Select value={data.variant} onValueChange={(v) => updateData({ variant: v })}>
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {variants.map((v) => (
                <SelectItem key={v} value={v}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            type="text"
            value={data.variant}
            onChange={(e) => updateData({ variant: e.target.value })}
            className="h-8 text-sm"
          />
        )}
      </div>

      {Object.keys(data.config).length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-1">Environment Overrides</div>
          {Object.entries(data.config).map(([key, value]) => (
            <div key={key} className="flex gap-1 mb-1">
              <div className="text-xs text-muted-foreground w-1/2 truncate pt-1">{key}</div>
              <Input
                type="text"
                value={value}
                onChange={(e) => updateConfig(key, e.target.value)}
                className="flex-1 h-7 text-xs"
              />
            </div>
          ))}
        </div>
      )}

      {instance && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="mb-2">
            <HealthBadge health={instance.health} />
          </div>
          {instance.web_uis.length > 0 && (
            <div className="mb-2">
              <div className="text-xs text-muted-foreground mb-1">Web UIs</div>
              {instance.web_uis.map((ui) => (
                <a
                  key={ui.name}
                  href={proxyUrl(ui.proxy_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-xs text-primary hover:underline mb-1"
                >
                  {ui.name}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
