import { useEffect, useRef, useState } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import HealthBadge from "../control-plane/HealthBadge";
import { proxyUrl, fetchComponents, getGeneratorStatus, startGenerator, stopGenerator, execCommand } from "../../api/client";
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
import { connectionColors, connectionLabels } from "../../lib/connectionMeta";
import { Eye, EyeOff } from "lucide-react";
import SqlEditorPanel from "../sql/SqlEditorPanel";
import SqlPlaybookPanel from "./SqlPlaybookPanel";

// --- Data Generator scenario metadata ---
const DG_SCENARIOS = [
  {
    id: "ecommerce-orders",
    name: "E-commerce Orders",
    description: "Retail order stream — products, customers, regions. Good for bar charts, KPIs, time-series.",
    rateProfiles: {
      low: { rows_per_batch: 100, batches_per_minute: 6 },
      medium: { rows_per_batch: 500, batches_per_minute: 12 },
      high: { rows_per_batch: 2000, batches_per_minute: 30 },
    },
  },
  {
    id: "iot-telemetry",
    name: "IoT Sensor Telemetry",
    description: "Industrial sensor readings — temperature, humidity, pressure, battery. High volume time-series.",
    rateProfiles: {
      low: { rows_per_batch: 200, batches_per_minute: 6 },
      medium: { rows_per_batch: 1000, batches_per_minute: 20 },
      high: { rows_per_batch: 5000, batches_per_minute: 60 },
    },
  },
  {
    id: "financial-txn",
    name: "Financial Transactions",
    description: "Banking transactions with risk scoring and compliance flags. Compliance/audit demo.",
    rateProfiles: {
      low: { rows_per_batch: 50, batches_per_minute: 4 },
      medium: { rows_per_batch: 300, batches_per_minute: 10 },
      high: { rows_per_batch: 1000, batches_per_minute: 20 },
    },
  },
] as const;

const DG_FORMATS = [
  { id: "parquet", name: "Parquet" },
  { id: "json", name: "JSON (NDJSON)" },
  { id: "csv", name: "CSV" },
  { id: "iceberg", name: "Iceberg (native)" },
  { id: "kafka", name: "Kafka (streaming)" },
] as const;

function rowsPerSec(scenario: string, profile: string): string {
  const s = DG_SCENARIOS.find((x) => x.id === scenario);
  if (!s) return "";
  const p = s.rateProfiles[profile as keyof typeof s.rateProfiles];
  if (!p) return "";
  const rps = Math.round((p.rows_per_batch * p.batches_per_minute) / 60);
  return `${profile.charAt(0).toUpperCase() + profile.slice(1)}: ~${rps} rows/sec (${p.rows_per_batch} rows × ${p.batches_per_minute} batches/min)`;
}

interface DataGeneratorPanelProps {
  nodeId: string;
  demoId: string | null;
  isRunning: boolean;
  config: Record<string, string>;
  updateConfig: (key: string, value: string) => void;
  onOpenSqlEditor?: (scenarioId: string) => void;
}

function DataGeneratorPanel({ nodeId, demoId, isRunning, config, updateConfig, onOpenSqlEditor }: DataGeneratorPanelProps) {
  const scenario = config["DG_SCENARIO"] ?? "ecommerce-orders";
  const writeMode = config["DG_WRITE_MODE"] ?? "iceberg";
  const format = config["DG_FORMAT"] ?? "parquet";
  const rateProfile = config["DG_RATE_PROFILE"] ?? "medium";

  const scenarioMeta = DG_SCENARIOS.find((s) => s.id === scenario);

  // Live generator status polling
  const [genStatus, setGenStatus] = useState<{
    state: string;
    rows_generated?: number;
    rows_per_sec?: number;
    batches_sent?: number;
    errors?: number;
  } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!demoId || !isRunning) {
      setGenStatus(null);
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    const poll = () => {
      getGeneratorStatus(demoId, nodeId)
        .then((s) => setGenStatus(s))
        .catch(() => {});
    };
    poll();
    pollRef.current = setInterval(poll, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [demoId, nodeId, isRunning]);

  const statusColors: Record<string, string> = {
    streaming: "text-green-400 bg-green-950/60 border-green-700/60",
    ramp_up: "text-amber-400 bg-amber-950/60 border-amber-700/60",
    error: "text-red-400 bg-red-950/60 border-red-700/60",
    idle: "text-zinc-400 bg-zinc-900/60 border-zinc-700/60",
    paused: "text-blue-400 bg-blue-950/60 border-blue-700/60",
  };

  const statusLabel: Record<string, string> = {
    streaming: "Streaming",
    ramp_up: "Ramping up",
    error: "Error",
    idle: "Idle",
    paused: "Paused",
  };

  const state = genStatus?.state ?? "idle";

  return (
    <div className="mt-3 pt-3 border-t border-border">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Dataset Configuration
      </div>

      {/* Scenario selector */}
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Dataset Scenario</label>
        <Select value={scenario} onValueChange={(v) => updateConfig("DG_SCENARIO", v)}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DG_SCENARIOS.map((s) => (
              <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {scenarioMeta && (
          <p className="text-[10px] text-muted-foreground mt-1">{scenarioMeta.description}</p>
        )}
      </div>

      {/* Write mode selector */}
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Write Mode</label>
        <Select value={writeMode} onValueChange={(v) => updateConfig("DG_WRITE_MODE", v)}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="iceberg">Iceberg (managed)</SelectItem>
            <SelectItem value="raw">Raw Files (external table)</SelectItem>
          </SelectContent>
        </Select>
        {writeMode === "iceberg" && (
          <p className="text-[10px] text-muted-foreground mt-1">
            Data written as Parquet through Iceberg catalog
          </p>
        )}
        {writeMode === "raw" && (
          <p className="text-[10px] text-muted-foreground mt-1">
            Files written directly to S3. Queryable via Hive external tables in Trino.
          </p>
        )}
      </div>

      {/* Format selector — only shown for raw mode (iceberg always uses Parquet internally) */}
      {writeMode === "raw" && (
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Output Format</label>
        <Select value={format} onValueChange={(v) => updateConfig("DG_FORMAT", v)}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DG_FORMATS.filter((f) => f.id !== "iceberg" && f.id !== "kafka").map((f) => (
              <SelectItem key={f.id} value={f.id}>{f.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      )}
      {writeMode !== "raw" && (
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Output Format</label>
        <Select value={format} onValueChange={(v) => updateConfig("DG_FORMAT", v)}>
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DG_FORMATS.map((f) => (
              <SelectItem key={f.id} value={f.id}>{f.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {format === "iceberg" && (
          <p className="text-[10px] text-amber-400/80 mt-1">
            Writes directly to AIStor Tables via Iceberg REST API. Requires Tables-enabled MinIO target.
          </p>
        )}
      </div>
      )}

      {/* Volume profile */}
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Data Rate</label>
        <div className="flex gap-1">
          {(["low", "medium", "high"] as const).map((p) => (
            <button
              key={p}
              onClick={() => updateConfig("DG_RATE_PROFILE", p)}
              className={`flex-1 py-1 text-xs rounded border transition-colors ${
                rateProfile === p
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-border hover:bg-accent"
              }`}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground mt-1">{rowsPerSec(scenario, rateProfile)}</p>
      </div>

      {/* Live status — only show when demo is running */}
      {isRunning && genStatus && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Generator Status
          </div>
          <div className="mb-2">
            <span className={`text-xs font-semibold rounded border px-2 py-0.5 ${statusColors[state] ?? statusColors.idle}`}>
              {statusLabel[state] ?? state}
            </span>
          </div>
          {state === "streaming" || state === "ramp_up" ? (
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Rows generated</span>
                <span className="font-mono text-foreground">{(genStatus.rows_generated ?? 0).toLocaleString()}</span>
              </div>
              {genStatus.rows_per_sec !== undefined && (
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Current rate</span>
                  <span className="font-mono text-foreground">{genStatus.rows_per_sec} rows/sec</span>
                </div>
              )}
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Batches sent</span>
                <span className="font-mono text-foreground">{genStatus.batches_sent ?? 0}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Errors</span>
                <span className={`font-mono ${(genStatus.errors ?? 0) > 0 ? "text-red-400" : "text-green-400"}`}>
                  {genStatus.errors ?? 0}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {onOpenSqlEditor && (
        <div className="mt-3 pt-3 border-t border-border">
          <button
            onClick={() => onOpenSqlEditor(scenario)}
            className="w-full py-1.5 text-xs font-medium rounded border border-emerald-700/50 text-emerald-400 bg-emerald-950/30 hover:bg-emerald-900/40 transition-colors"
          >
            Open SQL Editor
          </button>
        </div>
      )}
    </div>
  );
}

// --- RAG App Panel ---
interface RagAppPanelProps {
  nodeId: string;
  demoId: string | null;
  isRunning: boolean;
}

function RagAppPanel({ nodeId, demoId, isRunning }: RagAppPanelProps) {
  const [ragStatus, setRagStatus] = useState<{
    status?: string;
    minio_connected?: boolean;
    qdrant_connected?: boolean;
    models_loaded?: boolean;
    documents_ingested?: number;
    chunks_stored?: number;
  } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isRunning || !demoId) {
      setRagStatus(null);
      return;
    }
    const poll = async () => {
      try {
        const healthRes = await execCommand(demoId, nodeId,
          "wget -qO- http://localhost:8080/health 2>/dev/null");
        const statusRes = await execCommand(demoId, nodeId,
          "wget -qO- http://localhost:8080/status 2>/dev/null");
        const health = healthRes.exit_code === 0 ? JSON.parse(healthRes.stdout) : {};
        const status = statusRes.exit_code === 0 ? JSON.parse(statusRes.stdout) : {};
        setRagStatus({ ...health, ...status });
      } catch {}
    };
    poll();
    pollRef.current = setInterval(poll, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [isRunning, demoId, nodeId]);

  const handleIngestSample = async () => {
    if (!demoId) return;
    await execCommand(demoId, nodeId,
      "wget -qO- --post-data='' http://localhost:8080/ingest/sample 2>/dev/null");
  };

  const handleAskTest = async () => {
    if (!demoId) return;
    await execCommand(demoId, nodeId,
      "wget -qO- --post-data='{\"question\":\"What is MinIO?\"}' --header='Content-Type: application/json' http://localhost:8080/ask 2>/dev/null");
  };

  const handleReset = async () => {
    if (!demoId) return;
    await execCommand(demoId, nodeId,
      "wget -qO- --method=DELETE http://localhost:8080/collection 2>/dev/null");
  };

  return (
    <div className="mt-3 pt-3 border-t border-border space-y-3">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">RAG Pipeline</div>

      {ragStatus && (
        <>
          <div className="space-y-1 text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.minio_connected ? 'bg-green-500' : 'bg-red-500'}`} />
              MinIO
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.qdrant_connected ? 'bg-green-500' : 'bg-red-500'}`} />
              Qdrant
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.models_loaded ? 'bg-green-500' : 'bg-yellow-400 animate-pulse'}`} />
              Ollama models
            </div>
          </div>
          <div className="text-xs text-muted-foreground space-y-0.5">
            <div>Documents: {ragStatus.documents_ingested ?? 0}</div>
            <div>Chunks: {ragStatus.chunks_stored ?? 0}</div>
          </div>
        </>
      )}

      {isRunning && (
        <div className="space-y-1.5">
          <button onClick={handleIngestSample}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted transition-colors">
            Load sample docs
          </button>
          <button onClick={handleAskTest}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted transition-colors">
            Ask test question
          </button>
          <button onClick={handleReset}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted transition-colors text-destructive">
            Reset collection
          </button>
        </div>
      )}
    </div>
  );
}

// --- Ollama Panel ---
interface OllamaPanelProps {
  nodeId: string;
  demoId: string | null;
  isRunning: boolean;
}

function OllamaPanel({ nodeId, demoId, isRunning }: OllamaPanelProps) {
  const [models, setModels] = useState<string[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isRunning || !demoId) {
      setModels([]);
      return;
    }
    const poll = async () => {
      try {
        const res = await execCommand(demoId, nodeId, "ollama list 2>/dev/null");
        if (res.exit_code === 0) {
          const lines = res.stdout.trim().split("\n").slice(1); // skip header
          setModels(lines.map((l: string) => l.split(/\s+/)[0]).filter(Boolean));
        }
      } catch {}
    };
    poll();
    pollRef.current = setInterval(poll, 10000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [isRunning, demoId, nodeId]);

  return (
    <div className="mt-3 pt-3 border-t border-border space-y-2">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Ollama Models</div>
      {models.length > 0 ? (
        <div className="space-y-1">
          {models.map((m) => (
            <div key={m} className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="font-mono text-foreground">{m}</span>
            </div>
          ))}
        </div>
      ) : isRunning ? (
        <div className="text-xs text-muted-foreground flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
          Downloading models...
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">Not running</div>
      )}
    </div>
  );
}

function PasswordInput({ value, onChange, className }: { value: string; onChange: (v: string) => void; className?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={className ? `pr-8 ${className}` : "pr-8 h-8 text-sm"}
      />
      <button
        type="button"
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
        onClick={() => setShow((s) => !s)}
        tabIndex={-1}
      >
        {show ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

// Config schemas for cluster-level connection types (not in component manifests)
const clusterConfigSchemas: Record<string, ConnectionConfigField[]> = {
  "cluster-replication": [
    { key: "source_bucket", label: "Source Bucket", type: "string", default: "demo-bucket", required: false, options: [], description: "" },
    { key: "target_bucket", label: "Target Bucket", type: "string", default: "demo-bucket", required: false, options: [], description: "" },
    { key: "replication_mode", label: "Mode", type: "select", default: "async", required: false, options: ["async", "sync"], description: "async = eventually consistent, sync = write-through" },
    { key: "direction", label: "Direction", type: "select", default: "one-way", required: false, options: ["one-way", "bidirectional"], description: "" },
    { key: "bandwidth_limit", label: "Bandwidth Limit (MB/s)", type: "string", default: "0", required: false, options: [], description: "0 = unlimited" },
  ],
  "cluster-site-replication": [],
  "cluster-tiering": [
    { key: "source_bucket", label: "Source Bucket (Hot)", type: "string", default: "data", required: false, options: [], description: "" },
    { key: "tier_bucket", label: "Tier Bucket (Cold)", type: "string", default: "tiered", required: false, options: [], description: "" },
    { key: "tier_name", label: "Tier Name", type: "string", default: "COLD-TIER", required: false, options: [], description: "" },
    { key: "transition_days", label: "Transition After (days)", type: "string", default: "30", required: false, options: [], description: "" },
    { key: "policy_name", label: "Policy Name", type: "string", default: "auto-tier", required: false, options: [], description: "" },
  ],
};

export default function PropertiesPanel() {
  const { selectedNodeId, selectedEdgeId, nodes, edges, setNodes, setEdges, componentManifests } = useDiagramStore();
  const { instances, activeDemoId, demos } = useDemoStore();
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [sqlEditorOpen, setSqlEditorOpen] = useState(false);
  const [sqlEditorScenarioId, setSqlEditorScenarioId] = useState("ecommerce-orders");

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
    // Check cluster-level config schemas first
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
          // accepts side takes precedence on duplicate keys
          for (const f of accepts.config_schema) configFieldMap.set(f.key, f);
        }
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
    // Check if demo is running with data-generator + trino → show playbook
    const activeDemo = demos.find((d) => d.id === activeDemoId);
    const isRunning = activeDemo?.status === "running";
    const hasDataGen = nodes.some((n) => (n.data as any)?.componentId === "data-generator");
    const hasTrino = nodes.some((n) => (n.data as any)?.componentId === "trino");
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
              <PasswordInput
                value={gData.cluster_config?.root_password ?? "minioadmin"}
                onChange={(v) => updateGroup({ cluster_config: { ...(gData.cluster_config || {}), root_password: v } })}
                className="h-8 text-sm"
              />
            </div>
          </>
        )}
      </div>
    );
  }

  // --- Cluster properties ---
  if (selectedNode.type === "cluster") {
    const cData = selectedNode.data as any;
    const updateCluster = (patch: Record<string, any>) => {
      setNodes(nodes.map((n) => n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n));
    };
    const cNodeCount = cData.nodeCount || 4;
    const cDrivesPerNode = cData.drivesPerNode || 1;
    const totalDrives = cNodeCount * cDrivesPerNode;
    return (
      <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Cluster</div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Label</label>
          <Input type="text" value={cData.label ?? ""} onChange={(e) => updateCluster({ label: e.target.value })} className="h-8 text-sm" />
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Flavor</label>
          <Select value={cData.componentId || "minio"} onValueChange={(v) => updateCluster({ componentId: v })}>
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="minio">MinIO CE</SelectItem>
              <SelectItem value="minio-aistore">MinIO AIStore</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Node Count</label>
          <Select value={String(cNodeCount)} onValueChange={(v) => updateCluster({ nodeCount: parseInt(v) })}>
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="2">2 nodes</SelectItem>
              <SelectItem value="4">4 nodes</SelectItem>
              <SelectItem value="6">6 nodes</SelectItem>
              <SelectItem value="8">8 nodes</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Drives per Node</label>
          <Select value={String(cDrivesPerNode)} onValueChange={(v) => updateCluster({ drivesPerNode: parseInt(v) })}>
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">1 drive</SelectItem>
              <SelectItem value="2">2 drives</SelectItem>
              <SelectItem value="4">4 drives</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Root User</label>
          <Input
            type="text"
            value={cData.credentials?.root_user ?? "minioadmin"}
            onChange={(e) => updateCluster({ credentials: { ...(cData.credentials || {}), root_user: e.target.value } })}
            className="h-8 text-sm"
          />
        </div>
        <div className="mb-3">
          <label className="text-xs text-muted-foreground block mb-1">Root Password</label>
          <PasswordInput
            value={cData.credentials?.root_password ?? "minioadmin"}
            onChange={(v) => updateCluster({ credentials: { ...(cData.credentials || {}), root_password: v } })}
            className="h-8 text-sm"
          />
        </div>
        <div className="mb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={cData.mcpEnabled !== false}
              onChange={(e) => updateCluster({ mcpEnabled: e.target.checked })}
              className="rounded"
            />
            <span className="text-xs text-muted-foreground">Enable MCP AI Tools</span>
            {cData.mcpEnabled !== false && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-400 border border-violet-500/30">MCP</span>
            )}
          </label>
        </div>
        <div className="mb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={cData.aistorTablesEnabled === true}
              onChange={(e) => {
                const enabled = e.target.checked;
                updateCluster({ aistorTablesEnabled: enabled });
                // Auto-update existing edges from this cluster to Trino nodes
                const trinoNodeIds = nodes.filter((n) => (n.data as any)?.componentId === "trino").map((n) => n.id);
                if (trinoNodeIds.length > 0) {
                  const updatedEdges = edges.map((edge) => {
                    if (edge.source === selectedNodeId && trinoNodeIds.includes(edge.target)) {
                      const ed = edge.data as any;
                      const newType = enabled ? "aistor-tables" : "s3";
                      if (ed?.connectionType === "s3" || ed?.connectionType === "aistor-tables") {
                        return { ...edge, data: { ...ed, connectionType: newType } };
                      }
                    }
                    return edge;
                  });
                  if (updatedEdges.some((e, i) => e !== edges[i])) setEdges(updatedEdges);
                }
              }}
              className="rounded"
            />
            <span className="text-xs text-muted-foreground">Enable AIStor Tables</span>
            {cData.aistorTablesEnabled === true && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-700/15 text-blue-400 border border-blue-700/30">Tables</span>
            )}
          </label>
          <p className="text-[10px] text-muted-foreground mt-0.5 ml-5">
            Allows direct connection to Trino via AIStor Tables
          </p>
        </div>
        <div className="mt-3 pt-3 border-t border-border">
          <div className="text-xs text-muted-foreground">
            Total drives: {totalDrives} &bull; Parity: 50%
          </div>
        </div>
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
  const isExperience = demos.find((d) => d.id === activeDemoId)?.mode === "experience";

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
        {isExperience ? (
          <div className="text-sm text-muted-foreground">{data.variant}</div>
        ) : variants.length > 0 ? (
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
          <div className="text-xs text-muted-foreground mb-1">Environment{isExperience ? "" : " Overrides"}</div>
          {Object.entries(data.config).map(([key, value]) => (
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
          nodeId={selectedNodeId!}
          demoId={activeDemoId}
          isRunning={demos.find((d) => d.id === activeDemoId)?.status === "running"}
          config={data.config}
          updateConfig={updateConfig}
          onOpenSqlEditor={(scenarioId) => {
            setSqlEditorScenarioId(scenarioId);
            setSqlEditorOpen(true);
          }}
        />
      )}

      {data.componentId === "rag-app" && (
        <RagAppPanel
          nodeId={selectedNodeId!}
          demoId={activeDemoId}
          isRunning={demos.find((d) => d.id === activeDemoId)?.status === "running"}
        />
      )}

      {data.componentId === "ollama" && (
        <OllamaPanel
          nodeId={selectedNodeId!}
          demoId={activeDemoId}
          isRunning={demos.find((d) => d.id === activeDemoId)?.status === "running"}
        />
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
          {data.componentId === "metabase" && (
            <div className="mt-2 p-2 rounded border border-blue-500/20 bg-blue-500/5">
              <div className="text-[10px] font-medium text-blue-400 mb-1">Login Credentials</div>
              <div className="text-xs text-muted-foreground space-y-0.5">
                <div>Email: <span className="text-foreground font-mono">admin@demoforge.local</span></div>
                <div>Password: <span className="text-foreground font-mono">DemoForge123!</span></div>
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
