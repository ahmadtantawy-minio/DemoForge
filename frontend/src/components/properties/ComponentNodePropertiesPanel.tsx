import { useEffect, useMemo, useState } from "react";
import type { Edge, Node } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import ConfigSchemaForm from "./ConfigSchemaForm";
import ScenarioPicker from "./ScenarioPicker";
import SqlEditorPanel from "../sql/SqlEditorPanel";
import HealthBadge from "../control-plane/HealthBadge";
import { proxyUrl } from "../../api/client";
import type { ComponentNodeData, ComponentSummary, ContainerInstance, ScenarioOption } from "../../types";
import { useDiagramStore } from "../../stores/diagramStore";
import { fetchComponentScenarios } from "../../api/client";
import { mapEdgesForExternalSystemLabels, normalizeEsSinkMode } from "../../lib/externalSystemEdgeLabels";
import { nonemptyTrim } from "../../lib/utils";
import {
  AISTOR_TABLES_DEFAULT_CATALOG_NAME,
  AISTOR_TABLES_DEFAULT_ICEBERG_WAREHOUSE,
} from "../../lib/aistorTablesDefaults";
import { DataGeneratorPanel } from "./DataGeneratorPanel";
import { RagAppPanel } from "./RagAppPanel";
import { OllamaPanel } from "./OllamaPanel";
import { summarizeIamSimSpec } from "./minioIamSimSpec";

export interface EventProcessorRoutingInfo {
  webhookBucket: string;
  webhookPrefix: string;
  webhookEvents: string;
  s3TargetBucket: string;
  icebergWarehouse: string;
}

interface ComponentNodePropertiesPanelProps {
  selectedNodeId: string;
  data: ComponentNodeData;
  instance: ContainerInstance | undefined;
  componentDef: ComponentSummary | undefined;
  variants: string[];
  activeDemoId: string | null;
  isExperience: boolean;
  isRunning: boolean;
  nodes: Node[];
  edges: Edge[];
  setEdges: (edges: Edge[]) => void;
  eventProcessorRouting: EventProcessorRoutingInfo | null;
  updateData: (patch: Partial<ComponentNodeData>) => void;
  updateConfig: (key: string, value: string) => void;
  sqlEditorOpen: boolean;
  setSqlEditorOpen: (open: boolean) => void;
  sqlEditorScenarioId: string;
  setSqlEditorScenarioId: (id: string) => void;
  setDesignerWebUiOverlay: (o: { proxyPath: string; title: string } | null) => void;
}

export function ComponentNodePropertiesPanel({
  selectedNodeId,
  data,
  instance,
  componentDef,
  variants,
  activeDemoId,
  isExperience,
  isRunning,
  nodes,
  edges,
  setEdges,
  eventProcessorRouting,
  updateData,
  updateConfig,
  sqlEditorOpen,
  setSqlEditorOpen,
  sqlEditorScenarioId,
  setSqlEditorScenarioId,
  setDesignerWebUiOverlay,
}: ComponentNodePropertiesPanelProps) {
  const [esScenarios, setEsScenarios] = useState<ScenarioOption[]>([]);
  const manifestPropertyKeys = useMemo(
    () => new Set((componentDef?.properties ?? []).map((p) => p.key)),
    [componentDef?.properties],
  );

  useEffect(() => {
    if (data.componentId !== "external-system") {
      setEsScenarios([]);
      return;
    }
    void fetchComponentScenarios("external-system")
      .then((res) => setEsScenarios(res.scenarios))
      .catch(() => setEsScenarios([]));
  }, [data.componentId]);

  useEffect(() => {
    if (data.componentId !== "external-system" || isExperience) return;
    const scenario = esScenarios.find((s) => s.id === (data.config?.ES_SCENARIO ?? ""));
    const sink = normalizeEsSinkMode(data.config?.ES_SINK_MODE);
    const nodeRawFmt =
      nonemptyTrim(data.config?.ES_DG_FORMAT as string | undefined) ??
      nonemptyTrim(data.config?.DG_FORMAT as string | undefined) ??
      null;
    const cur = useDiagramStore.getState().edges;
    const next = mapEdgesForExternalSystemLabels(cur, selectedNodeId, sink, scenario, nodeRawFmt);
    let changed = false;
    for (const e of cur) {
      if (e.source !== selectedNodeId) continue;
      const ct = (e.data as { connectionType?: string } | undefined)?.connectionType;
      if (ct !== "s3" && ct !== "aistor-tables") continue;
      const ne = next.find((x) => x.id === e.id);
      const oldLabel = (e.data as { label?: string } | undefined)?.label ?? "";
      const newLabel = (ne?.data as { label?: string } | undefined)?.label ?? "";
      const oldSink = (e.data as { connectionConfig?: { es_sink_mode?: string } } | undefined)?.connectionConfig?.es_sink_mode;
      if (oldLabel !== newLabel || oldSink !== sink) {
        changed = true;
        break;
      }
    }
    if (changed) setEdges(next);
  }, [
    data.componentId,
    data.config?.ES_SCENARIO,
    data.config?.ES_SINK_MODE,
    data.config?.ES_DG_FORMAT,
    data.config?.DG_FORMAT,
    esScenarios,
    isExperience,
    selectedNodeId,
    setEdges,
  ]);

  const minioEdition = data.config?.MINIO_EDITION || "ce";
  const isAIStorEdition = minioEdition === "aistor" || minioEdition === "aistor-edge";
  const minioImageRef =
    minioEdition === "aistor-edge"
      ? "quay.io/minio/aistor/minio:edge"
      : minioEdition === "aistor"
        ? "quay.io/minio/aistor/minio:latest"
        : "quay.io/minio/minio:latest";

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Properties</div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Display Name</label>
        {isExperience ? (
          <div className="text-sm font-medium text-foreground">{data.displayName || data.label || data.componentId}</div>
        ) : (
          <Input
            type="text"
            value={data.displayName ?? ""}
            onChange={(e) => updateData({ displayName: e.target.value })}
            placeholder={data.label || data.componentId}
            className="h-8 text-sm"
          />
        )}
      </div>

      <div className="mb-3">
        <div className="text-xs text-muted-foreground mb-1">Component</div>
        <div className="text-sm font-medium text-foreground">{componentDef?.name || data.label}</div>
        {data.componentId === "minio" && !isExperience ? (
          <>
            <Select
              value={minioEdition}
              onValueChange={(v) => {
                updateConfig("MINIO_EDITION", v);
                if (v === "ce") updateData({ aistorTablesEnabled: false, mcpEnabled: false });
              }}
            >
              <SelectTrigger className="w-full h-8 text-sm mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ce">Community (CE)</SelectItem>
                <SelectItem value="aistor">AIStor (Enterprise)</SelectItem>
                <SelectItem value="aistor-edge">AIStor (Edge)</SelectItem>
              </SelectContent>
            </Select>
            <div className="text-xs text-muted-foreground mt-1 font-mono bg-muted px-1.5 py-0.5 rounded inline-block">{minioImageRef}</div>
            {isAIStorEdition && (
              <div className="mt-2 space-y-1.5">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-primary"
                    checked={!!data.aistorTablesEnabled}
                    onChange={(e) => {
                      const enabled = e.target.checked;
                      const wh =
                        (data.config?.ICEBERG_WAREHOUSE || "").trim() ||
                        AISTOR_TABLES_DEFAULT_ICEBERG_WAREHOUSE;
                      const catalogHint =
                        (data.config?.AISTOR_TABLES_CATALOG_NAME || "").trim() ||
                        AISTOR_TABLES_DEFAULT_CATALOG_NAME;
                      updateData(
                        enabled
                          ? {
                              aistorTablesEnabled: true,
                              config: {
                                ...data.config,
                                ICEBERG_WAREHOUSE: wh,
                                AISTOR_TABLES_CATALOG_NAME: catalogHint,
                              },
                            }
                          : { aistorTablesEnabled: false }
                      );
                    }}
                  />
                  <span className="text-xs text-foreground">AIStor Tables (Iceberg REST)</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-primary"
                    checked={!!data.mcpEnabled}
                    onChange={(e) => updateData({ mcpEnabled: e.target.checked })}
                  />
                  <span className="text-xs text-foreground">MCP Server</span>
                </label>
                {data.aistorTablesEnabled && (
                  <div className="mt-2 space-y-2 border border-border rounded-md p-2 bg-muted/20">
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">Catalog name</label>
                      <Input
                        type="text"
                        value={data.config?.AISTOR_TABLES_CATALOG_NAME ?? ""}
                        placeholder={AISTOR_TABLES_DEFAULT_CATALOG_NAME}
                        onChange={(e) => updateConfig("AISTOR_TABLES_CATALOG_NAME", e.target.value)}
                        className="h-8 text-sm font-mono"
                      />
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        Used for Trino when this MinIO connects via AIStor Tables (default{" "}
                        {AISTOR_TABLES_DEFAULT_CATALOG_NAME}).
                      </p>
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">Namespace/warehouse name</label>
                      <Input
                        type="text"
                        value={data.config?.ICEBERG_WAREHOUSE ?? ""}
                        placeholder={AISTOR_TABLES_DEFAULT_ICEBERG_WAREHOUSE}
                        onChange={(e) => updateConfig("ICEBERG_WAREHOUSE", e.target.value)}
                        className="h-8 text-sm font-mono"
                      />
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        REST catalog warehouse (default {AISTOR_TABLES_DEFAULT_ICEBERG_WAREHOUSE}).
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          <>
            {data.componentId === "nginx" && !isExperience && (
              <Select value={data.config?.mode || "round-robin"} onValueChange={(v) => updateConfig("mode", v)}>
                <SelectTrigger className="w-full h-8 text-sm mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="round-robin">Round Robin</SelectItem>
                  <SelectItem value="least-conn">Least Connections</SelectItem>
                  <SelectItem value="ip-hash">IP Hash</SelectItem>
                  <SelectItem value="failover">Failover (Active/Passive)</SelectItem>
                </SelectContent>
              </Select>
            )}
            {data.componentId !== "minio" && data.componentId !== "nginx" && variants.length > 0 && !isExperience && (
              <Select value={data.variant} onValueChange={(v) => updateData({ variant: v })}>
                <SelectTrigger className="w-full h-8 text-sm mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {variants.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {componentDef?.image && (
              <div className="text-xs text-muted-foreground mt-1 font-mono bg-muted px-1.5 py-0.5 rounded inline-block">{componentDef.image}</div>
            )}
          </>
        )}
      </div>

      {data.componentId === "external-system" && !isExperience && (
        <>
          <ScenarioPicker
            currentScenario={data.config?.ES_SCENARIO ?? ""}
            catalogName={
              (edges.find((e) => e.source === selectedNodeId && (e.data as { connectionConfig?: { catalog_name?: string } })?.connectionConfig?.catalog_name)?.data as {
                connectionConfig?: { catalog_name?: string };
              })?.connectionConfig?.catalog_name
            }
            onScenarioChange={(scenarioId, scenario) => {
              const currentDisplayName = data.displayName ?? "";
              const needsNameUpdate =
                !currentDisplayName ||
                currentDisplayName === "External System" ||
                currentDisplayName === (data.label ?? "");
              const sink = normalizeEsSinkMode(data.config?.ES_SINK_MODE);
              const nodeRawFmt =
                nonemptyTrim(data.config?.ES_DG_FORMAT as string | undefined) ??
                nonemptyTrim(data.config?.DG_FORMAT as string | undefined) ??
                null;
              updateData({
                config: { ...data.config, ES_SCENARIO: scenarioId },
                ...(needsNameUpdate ? { displayName: scenario.default_name } : {}),
              });
              const currentEdges = useDiagramStore.getState().edges;
              setEdges(mapEdgesForExternalSystemLabels(currentEdges, selectedNodeId, sink, scenario, nodeRawFmt));
            }}
          />
          <div className="mb-3">
            <label className="text-xs text-muted-foreground block mb-1">Data sink</label>
            <p className="text-[10px] text-muted-foreground/90 mb-1.5 leading-snug">
              Files only lands CSV/objects in MinIO for Spark or downstream ETL. Files + catalog also registers Iceberg tables when the catalog is available (PyIceberg when supported, otherwise Trino).
            </p>
            <Select
              value={normalizeEsSinkMode(data.config?.ES_SINK_MODE)}
              onValueChange={(v) => {
                const sink = normalizeEsSinkMode(v);
                const scenario = esScenarios.find((s) => s.id === (data.config?.ES_SCENARIO ?? ""));
                const nodeRawFmt =
                  nonemptyTrim(data.config?.ES_DG_FORMAT as string | undefined) ??
                  nonemptyTrim(data.config?.DG_FORMAT as string | undefined) ??
                  null;
                updateData({ config: { ...data.config, ES_SINK_MODE: v } });
                const currentEdges = useDiagramStore.getState().edges;
                setEdges(mapEdgesForExternalSystemLabels(currentEdges, selectedNodeId, sink, scenario, nodeRawFmt));
              }}
            >
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="files_and_iceberg">Files + Iceberg (default)</SelectItem>
                <SelectItem value="files_only">Files only (raw landing / objects)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="mb-3">
            <label className="text-xs text-muted-foreground block mb-1">Raw file format</label>
            <p className="text-[10px] text-muted-foreground/90 mb-1.5 leading-snug">
              Object format for Files only mode and for Data Generator scenarios (sets{" "}
              <span className="font-mono">DG_FORMAT</span> / <span className="font-mono">ES_DG_FORMAT</span> in the
              container). Configure here instead of on the MinIO connection.
            </p>
            <Select
              value={(data.config?.ES_DG_FORMAT || data.config?.DG_FORMAT || "csv").toLowerCase()}
              onValueChange={(v) => {
                const sink = normalizeEsSinkMode(data.config?.ES_SINK_MODE);
                const scenario = esScenarios.find((s) => s.id === (data.config?.ES_SCENARIO ?? ""));
                updateData({ config: { ...data.config, ES_DG_FORMAT: v, DG_FORMAT: v } });
                const currentEdges = useDiagramStore.getState().edges;
                setEdges(mapEdgesForExternalSystemLabels(currentEdges, selectedNodeId, sink, scenario, v));
              }}
            >
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="csv">csv</SelectItem>
                <SelectItem value="json">json</SelectItem>
                <SelectItem value="parquet">parquet</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {data.componentId === "spark-etl-job" && !isExperience && (
        <div className="mb-3 space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Schedule</label>
            <p className="text-[10px] text-muted-foreground/90 mb-1 leading-snug">
              on_deploy_once runs spark-submit once after Spark is healthy. interval re-runs on a timer. manual idles the container for a narrated demo.
            </p>
            <Select value={data.config?.JOB_SCHEDULE ?? "on_deploy_once"} onValueChange={(v) => updateConfig("JOB_SCHEDULE", v)}>
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="on_deploy_once">On deploy (once)</SelectItem>
                <SelectItem value="interval">Interval (repeat)</SelectItem>
                <SelectItem value="manual">Manual</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {(data.config?.JOB_SCHEDULE ?? "on_deploy_once") === "interval" && (
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Interval (seconds)</label>
              <Input
                type="number"
                min={60}
                step={60}
                value={data.config?.JOB_INTERVAL_SEC ?? "300"}
                onChange={(e) => updateConfig("JOB_INTERVAL_SEC", e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
          )}
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Job type</label>
            <p className="text-xs text-muted-foreground border rounded-md px-2 py-1.5 bg-muted/30">
              Raw → Iceberg — load CSV or JSON from MinIO (S3A) and write into the Iceberg REST catalog (
              <code className="text-[10px]">/_iceberg</code> on AIStor Tables).
            </p>
          </div>
          <div className="border border-border rounded-md p-2 space-y-2 bg-muted/15">
            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
              Target Iceberg table (catalog write)
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Namespace (schema)</label>
              <Input
                value={data.config?.ICEBERG_TARGET_NAMESPACE ?? ""}
                placeholder="analytics"
                onChange={(e) => updateConfig("ICEBERG_TARGET_NAMESPACE", e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Target table name</label>
              <Input
                value={data.config?.ICEBERG_TARGET_TABLE ?? ""}
                placeholder="events_from_raw"
                onChange={(e) => updateConfig("ICEBERG_TARGET_TABLE", e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <p className="text-[10px] text-muted-foreground font-mono break-all">
              Spark catalog <span className="text-foreground">demoforge_rest</span> →{" "}
              <span className="text-foreground">
                {(data.config?.ICEBERG_TARGET_NAMESPACE || "analytics").trim() || "analytics"}.
                {(data.config?.ICEBERG_TARGET_TABLE || "events_from_raw").trim() || "events_from_raw"}
              </span>
            </p>
          </div>
          <div className="border border-border rounded-md p-2 space-y-2 bg-muted/15">
            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
              MinIO buckets (S3A)
            </div>
            <p className="text-[10px] text-muted-foreground leading-snug">
              Configure landing and warehouse buckets on the job — MinIO→job edges only set input vs output.
            </p>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Raw landing bucket</label>
              <Input
                value={data.config?.RAW_LANDING_BUCKET ?? ""}
                placeholder="raw-logs"
                onChange={(e) => updateConfig("RAW_LANDING_BUCKET", e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Warehouse bucket</label>
              <Input
                value={data.config?.WAREHOUSE_BUCKET ?? ""}
                placeholder="warehouse"
                onChange={(e) => updateConfig("WAREHOUSE_BUCKET", e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Object key prefix (optional)</label>
              <Input
                value={data.config?.INPUT_OBJECT_PREFIX ?? ""}
                onChange={(e) => updateConfig("INPUT_OBJECT_PREFIX", e.target.value)}
                placeholder="folder/subfolder/"
                className="h-8 text-sm font-mono"
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Raw input format</label>
            <Select
              value={(data.config?.RAW_INPUT_FORMAT || data.config?.INPUT_FORMAT || "csv").toLowerCase()}
              onValueChange={(v) => {
                const next = v === "json" ? "json" : "csv";
                const curGlob = (data.config?.INPUT_GLOB || "").trim();
                let nextGlob = curGlob;
                if (next === "json" && (curGlob === "*.csv" || curGlob === "")) nextGlob = "*.json";
                if (next === "csv" && (curGlob === "*.json" || curGlob === "")) nextGlob = "*.csv";
                updateData({
                  config: {
                    ...data.config,
                    RAW_INPUT_FORMAT: next,
                    ...(nextGlob !== curGlob ? { INPUT_GLOB: nextGlob } : {}),
                  },
                });
              }}
            >
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="csv">CSV</SelectItem>
                <SelectItem value="json">JSON (JSON Lines or multi-line)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Input object glob</label>
            <Input
              value={data.config?.INPUT_GLOB ?? ""}
              onChange={(e) => updateConfig("INPUT_GLOB", e.target.value)}
              placeholder={
                (data.config?.RAW_INPUT_FORMAT || data.config?.INPUT_FORMAT || "csv").toLowerCase() === "json"
                  ? "*.json"
                  : "*.csv"
              }
              className="h-8 text-sm font-mono"
            />
            <p className="text-[10px] text-muted-foreground mt-0.5">
              Path under the raw landing bucket, e.g. <span className="font-mono">*.csv</span> or{" "}
              <span className="font-mono">landing/*.json</span>.
            </p>
          </div>
          {(data.config?.RAW_INPUT_FORMAT || data.config?.INPUT_FORMAT || "csv").toLowerCase() === "json" && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-primary"
                checked={(data.config?.JSON_MULTILINE || "").toLowerCase() === "true"}
                onChange={(e) => updateConfig("JSON_MULTILINE", e.target.checked ? "true" : "false")}
              />
              <span className="text-xs text-foreground">JSON: multi-line documents (Spark multiLine)</span>
            </label>
          )}
        </div>
      )}

      {data.componentId === "event-processor" && !isExperience && (
        <>
          <ScenarioPicker
            componentId="event-processor"
            label="Action scenario"
            currentScenario={data.config?.EP_ACTION_SCENARIO ?? ""}
            onScenarioChange={(scenarioId, scenario) => {
              const currentDisplayName = data.displayName ?? "";
              const needsNameUpdate =
                !currentDisplayName ||
                currentDisplayName === "Event Processor" ||
                currentDisplayName === (data.label ?? "");
              updateData({
                config: { ...data.config, EP_ACTION_SCENARIO: scenarioId },
                ...(needsNameUpdate ? { displayName: scenario.default_name || scenario.name } : {}),
              });
            }}
          />
          <div className="mb-3">
            <label className="text-xs text-muted-foreground block mb-1">Processing mode</label>
            <p className="text-[10px] text-muted-foreground/90 mb-1.5 leading-snug">
              Controls whether incoming events are only recorded (observe) or passed to scenario actions (process) when actions are enabled.
            </p>
            <Select value={data.config?.EP_MODE ?? "process"} onValueChange={(v) => updateConfig("EP_MODE", v)}>
              <SelectTrigger className="w-full h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="observe">observe (log only)</SelectItem>
                <SelectItem value="process">process (run scenario)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {eventProcessorRouting && (
            <div className="mb-3 rounded-md border border-border/70 bg-muted/25 px-2.5 py-2 space-y-2">
              <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Buckets (from edges)</div>
              <div className="space-y-1 text-xs">
                <div>
                  <span className="text-muted-foreground">Webhook filter bucket</span>
                  <span
                    className="float-right font-mono text-foreground max-w-[55%] text-right truncate"
                    title={eventProcessorRouting.webhookBucket || "(all buckets)"}
                  >
                    {eventProcessorRouting.webhookBucket || "— (all buckets)"}
                  </span>
                </div>
                {eventProcessorRouting.webhookPrefix ? (
                  <div>
                    <span className="text-muted-foreground">Key prefix</span>
                    <span
                      className="float-right font-mono text-foreground max-w-[55%] text-right truncate"
                      title={eventProcessorRouting.webhookPrefix}
                    >
                      {eventProcessorRouting.webhookPrefix}
                    </span>
                  </div>
                ) : null}
                {eventProcessorRouting.webhookEvents ? (
                  <div>
                    <span className="text-muted-foreground">Events</span>
                    <span
                      className="float-right font-mono text-[10px] text-foreground max-w-[55%] text-right truncate"
                      title={eventProcessorRouting.webhookEvents}
                    >
                      {eventProcessorRouting.webhookEvents}
                    </span>
                  </div>
                ) : null}
                <div>
                  <span className="text-muted-foreground">S3 write target</span>
                  <span
                    className="float-right font-mono text-foreground max-w-[55%] text-right truncate"
                    title={eventProcessorRouting.s3TargetBucket || "Connect S3 edge → MinIO"}
                  >
                    {eventProcessorRouting.s3TargetBucket || "— (set on S3 edge)"}
                  </span>
                </div>
                {eventProcessorRouting.icebergWarehouse ? (
                  <div>
                    <span className="text-muted-foreground">Iceberg warehouse</span>
                    <span className="float-right font-mono text-foreground max-w-[55%] text-right truncate">
                      {eventProcessorRouting.icebergWarehouse}
                    </span>
                  </div>
                ) : null}
              </div>
              <p className="text-[10px] text-muted-foreground leading-snug pt-0.5 border-t border-border/50">
                Edit buckets on the <span className="text-foreground/90">webhook</span> and <span className="text-foreground/90">S3</span> edges, not here.
              </p>
            </div>
          )}
        </>
      )}

      {(componentDef?.properties?.length ?? 0) > 0 && (
        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-2">Configuration</div>
          {isExperience ? (
            componentDef!.properties!.map((field) => {
              const raw = data.config[field.key] ?? field.default ?? "";
              const display =
                field.type === "iam_sim_spec"
                  ? summarizeIamSimSpec(String(raw))
                  : field.type === "s3_simulated_identity"
                    ? String(raw ?? "").trim()
                      ? String(raw)
                      : "Root (administrator)"
                    : String(raw ?? "");
              return (
                <div key={field.key} className="flex gap-1 mb-1">
                  <div className="text-xs text-muted-foreground w-1/2 truncate pt-1">{field.label}</div>
                  <div className="flex-1 text-xs text-foreground pt-1 truncate" title={field.type === "iam_sim_spec" ? String(raw) : undefined}>
                    {display}
                  </div>
                </div>
              );
            })
          ) : (
            <ConfigSchemaForm
              fields={componentDef!.properties!}
              values={data.config}
              onChange={updateConfig}
              diagramContext={{ nodeId: selectedNodeId, nodes, edges }}
            />
          )}
        </div>
      )}

      {Object.keys(data.config).filter((k) => {
        if (manifestPropertyKeys.has(k)) return false;
        if (k === "MINIO_EDITION" || (data.componentId === "nginx" && k === "mode")) return false;
        if (data.componentId === "event-processor") {
          if (k === "EP_ACTION_SCENARIO" || k === "EP_MODE") return false;
          if (k.startsWith("S3_") || k.startsWith("ICEBERG_") || k.startsWith("EP_WEBHOOK") || k === "EP_MINIO_NOTIFY_SUFFIX") return false;
        }
        return true;
      }).length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-1">Environment{isExperience ? "" : " Overrides"}</div>
          {Object.entries(data.config)
            .filter(([key]) => {
              if (manifestPropertyKeys.has(key)) return false;
              if (key === "MINIO_EDITION" || (data.componentId === "nginx" && key === "mode")) return false;
              if (data.componentId === "event-processor") {
                if (key === "EP_ACTION_SCENARIO" || key === "EP_MODE") return false;
                if (key.startsWith("S3_") || key.startsWith("ICEBERG_") || key.startsWith("EP_WEBHOOK") || key === "EP_MINIO_NOTIFY_SUFFIX") return false;
              }
              return true;
            })
            .map(([key, value]) => (
              <div key={key} className="flex gap-1 mb-1">
                <div className="text-xs text-muted-foreground w-1/2 truncate pt-1">{key}</div>
                {isExperience ? (
                  <div className="flex-1 text-xs font-mono text-foreground pt-1 truncate">{value}</div>
                ) : (
                  <Input
                    type="text"
                    value={value}
                    onChange={(e) => updateConfig(key, e.target.value)}
                    className="flex-1 h-7 text-xs"
                  />
                )}
              </div>
            ))}
        </div>
      )}

      {data.componentId === "data-generator" && (
        <DataGeneratorPanel
          nodeId={selectedNodeId}
          demoId={activeDemoId}
          isRunning={isRunning}
          config={data.config}
          updateConfig={updateConfig}
          onOpenSqlEditor={(scenarioId) => {
            setSqlEditorScenarioId(scenarioId);
            setSqlEditorOpen(true);
          }}
        />
      )}

      {data.componentId === "rag-app" && <RagAppPanel nodeId={selectedNodeId} demoId={activeDemoId} isRunning={isRunning} />}

      {data.componentId === "ollama" && <OllamaPanel nodeId={selectedNodeId} demoId={activeDemoId} isRunning={isRunning} />}

      {instance && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="mb-2">
            <HealthBadge health={instance.health} />
          </div>
          {instance.web_uis.length > 0 && (
            <div className="mb-2">
              <div className="text-xs text-muted-foreground mb-1">Web UIs</div>
              {instance.web_uis.map((ui) =>
                data.componentId === "event-processor" ? (
                  <button
                    key={ui.name}
                    type="button"
                    className="block w-full text-left text-xs text-primary hover:underline mb-1"
                    onClick={() => setDesignerWebUiOverlay({ proxyPath: ui.proxy_url, title: ui.name })}
                  >
                    {ui.name}
                  </button>
                ) : (
                  <a
                    key={ui.name}
                    href={proxyUrl(ui.proxy_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block text-xs text-primary hover:underline mb-1"
                  >
                    {ui.name}
                  </a>
                )
              )}
            </div>
          )}
          {data.componentId === "metabase" && (
            <div className="mt-2 p-2 rounded border border-blue-500/20 bg-blue-500/5">
              <div className="text-[10px] font-medium text-blue-400 mb-1">Login Credentials</div>
              <div className="text-xs text-muted-foreground space-y-0.5">
                <div>
                  Email: <span className="text-foreground font-mono">admin@demoforge.local</span>
                </div>
                <div>
                  Password: <span className="text-foreground font-mono">DemoForge123!</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeDemoId && (
        <SqlEditorPanel
          open={sqlEditorOpen}
          onOpenChange={setSqlEditorOpen}
          demoId={activeDemoId}
          scenarioId={sqlEditorScenarioId}
        />
      )}
    </div>
  );
}
