import type { Edge } from "@xyflow/react";
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
import type { ComponentNodeData, ComponentSummary, ContainerInstance } from "../../types";
import { useDiagramStore } from "../../stores/diagramStore";
import { DataGeneratorPanel } from "./DataGeneratorPanel";
import { RagAppPanel } from "./RagAppPanel";
import { OllamaPanel } from "./OllamaPanel";

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
                    onChange={(e) => updateData({ aistorTablesEnabled: e.target.checked })}
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
            updateData({
              config: { ...data.config, ES_SCENARIO: scenarioId },
              ...(needsNameUpdate ? { displayName: scenario.default_name } : {}),
            });
            const currentEdges = useDiagramStore.getState().edges;
            const primaryMode = scenario.datasets?.[0]?.generation_mode ?? "";
            setEdges(
              currentEdges.map((e) => {
                if (e.source !== selectedNodeId) return e;
                const ct = (e.data as { connectionType?: string } | undefined)?.connectionType as string | undefined;
                const prefix = ct === "aistor-tables" ? "Iceberg" : ct === "s3" ? "S3" : null;
                const parts = [prefix, scenario.format, scenario.primary_table].filter(Boolean);
                const label = parts.length > 0 ? parts.join(" · ") : (e.data as { label?: string })?.label;
                return {
                  ...e,
                  data: {
                    ...e.data,
                    ...(label ? { label } : {}),
                    connectionConfig: {
                      ...((e.data as { connectionConfig?: Record<string, string> })?.connectionConfig ?? {}),
                      generation_mode: primaryMode,
                    },
                  },
                };
              })
            );
          }}
        />
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
            componentDef!.properties!.map((field) => (
              <div key={field.key} className="flex gap-1 mb-1">
                <div className="text-xs text-muted-foreground w-1/2 truncate pt-1">{field.label}</div>
                <div className="flex-1 text-xs font-mono text-foreground pt-1 truncate">
                  {data.config[field.key] ?? field.default ?? ""}
                </div>
              </div>
            ))
          ) : (
            <ConfigSchemaForm fields={componentDef!.properties!} values={data.config} onChange={updateConfig} />
          )}
        </div>
      )}

      {Object.keys(data.config).filter((k) => {
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
