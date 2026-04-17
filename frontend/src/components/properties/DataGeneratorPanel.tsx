import { useEffect, useRef, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getGeneratorStatus } from "../../api/client";

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
  {
    id: "clickstream",
    name: "Web Clickstream",
    description: "Web browsing events — page views, clicks, sessions, conversions. High-volume streaming.",
    rateProfiles: {
      low: { rows_per_batch: 50, batches_per_minute: 6 },
      medium: { rows_per_batch: 200, batches_per_minute: 30 },
      high: { rows_per_batch: 1000, batches_per_minute: 60 },
    },
  },
  {
    id: "customer-360",
    name: "Customer 360",
    description: "Customer analytics with transactions — segments, merchants, MENA-weighted countries.",
    rateProfiles: {
      low: { rows_per_batch: 50, batches_per_minute: 4 },
      medium: { rows_per_batch: 200, batches_per_minute: 10 },
      high: { rows_per_batch: 1000, batches_per_minute: 30 },
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

export function DataGeneratorPanel({
  nodeId,
  demoId,
  isRunning,
  config,
  updateConfig,
  onOpenSqlEditor,
}: DataGeneratorPanelProps) {
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
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
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
              <SelectItem key={s.id} value={s.id}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {scenarioMeta && <p className="text-[10px] text-muted-foreground mt-1">{scenarioMeta.description}</p>}
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
          <p className="text-[10px] text-muted-foreground mt-1">Data written as Parquet through Iceberg catalog</p>
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
                <SelectItem key={f.id} value={f.id}>
                  {f.name}
                </SelectItem>
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
                <SelectItem key={f.id} value={f.id}>
                  {f.name}
                </SelectItem>
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
              type="button"
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
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Generator Status</div>
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
            type="button"
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
