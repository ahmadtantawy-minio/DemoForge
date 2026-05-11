import type { Edge, Node } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import ConfigSchemaForm from "./ConfigSchemaForm";
import { getConnectionColor, getConnectionLabel } from "../../lib/connectionMeta";
import { nonemptyTrim } from "../../lib/utils";
import type { ComponentEdgeData, ConnectionConfigField, ConnectionsDef } from "../../types";
import { clusterConfigSchemas } from "./clusterConfigSchemas";

/** Map legacy `tier_bucket`-only configs to `cold_bucket` + empty prefix for the form. */
function clusterTieringFormValues(raw: Record<string, unknown> | undefined): Record<string, unknown> {
  const c = { ...(raw ?? {}) };
  const hasCold = Object.prototype.hasOwnProperty.call(c, "cold_bucket");
  const hasPrefix = Object.prototype.hasOwnProperty.call(c, "tier_prefix");
  const legacyTb = c["tier_bucket"];
  if (!hasCold && !hasPrefix && legacyTb != null && String(legacyTb).trim() !== "") {
    return { ...c, cold_bucket: legacyTb, tier_prefix: "" };
  }
  return c;
}

interface EdgePropertiesPanelProps {
  selectedEdgeId: string;
  edges: Edge[];
  nodes: Node[];
  setEdges: (edges: Edge[]) => void;
  componentManifests: Record<string, ConnectionsDef>;
}

export function EdgePropertiesPanel({
  selectedEdgeId,
  edges,
  nodes,
  setEdges,
  componentManifests,
}: EdgePropertiesPanelProps) {
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
  const color = getConnectionColor(connType);
  const label = getConnectionLabel(connType);

  const sourceNode = nodes.find((n) => n.id === selectedEdge.source);
  const targetNode = nodes.find((n) => n.id === selectedEdge.target);

  const sourceComponentId = (sourceNode?.data as { componentId?: string } | undefined)?.componentId;
  const targetComponentId = (targetNode?.data as { componentId?: string } | undefined)?.componentId;
  const sourceConns = sourceComponentId ? componentManifests[sourceComponentId] : null;
  const targetConns = targetComponentId ? componentManifests[targetComponentId] : null;

  const configFieldMap = new Map<string, ConnectionConfigField>();
  const clusterSchema = clusterConfigSchemas[connType];
  if (clusterSchema) {
    for (const f of clusterSchema) configFieldMap.set(f.key, f);
  } else {
    if (sourceConns) {
      const provides = sourceConns.provides.find((p) => p.type === connType);
      if (provides?.config_schema) {
        for (const f of provides.config_schema) configFieldMap.set(f.key, f);
      }
    }
    if (targetConns) {
      const accepts = targetConns.accepts.find((a) => a.type === connType);
      if (accepts?.config_schema) {
        for (const f of accepts.config_schema) configFieldMap.set(f.key, f);
      }
    }
  }
  const configFields = Array.from(configFieldMap.values());

  const updateEdgeData = (patch: Partial<ComponentEdgeData>) => {
    setEdges(
      edges.map((e) => (e.id === selectedEdgeId ? { ...e, data: { ...e.data, ...patch } } : e))
    );
  };

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Connection Properties</div>

      <div className="mb-3">
        <div className="text-xs text-muted-foreground mb-1">Type</div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: color }} />
          <span className="text-sm font-medium text-foreground">{label}</span>
        </div>
      </div>

      <div className="mb-3">
        <div className="text-xs text-muted-foreground mb-1">Direction</div>
        <div className="text-sm text-foreground">
          {(sourceNode?.data as { label?: string } | undefined)?.label ?? selectedEdge.source}
          <span className="text-muted-foreground mx-1">&rarr;</span>
          {(targetNode?.data as { label?: string } | undefined)?.label ?? selectedEdge.target}
        </div>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Label</label>
        <Input
          type="text"
          value={edgeData.label ?? ""}
          onChange={(e) => updateEdgeData({ label: e.target.value })}
          onBlur={() => {
            const raw = edgeData.label;
            const t = nonemptyTrim(raw);
            if (t === null) {
              if (raw !== undefined && String(raw).trim() === "") updateEdgeData({ label: undefined });
            } else if (t !== raw) {
              updateEdgeData({ label: t });
            }
          }}
          placeholder={
            targetComponentId === "spark-etl-job" && (connType === "s3" || connType === "aistor-tables")
              ? "Auto: CSV|JSON → table (from job)"
              : "Optional label"
          }
          className="h-8 text-sm"
        />
        {targetComponentId === "spark-etl-job" && (connType === "s3" || connType === "aistor-tables") && (
          <p className="text-[10px] text-muted-foreground mt-1">
            Leave empty to show a dynamic label from the Apache Spark job (raw format → target table; output edges
            show Iceberg → table).
          </p>
        )}
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
            values={
              connType === "cluster-tiering"
                ? clusterTieringFormValues((edgeData.connectionConfig ?? {}) as Record<string, unknown>)
                : edgeData.connectionConfig ?? {}
            }
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
