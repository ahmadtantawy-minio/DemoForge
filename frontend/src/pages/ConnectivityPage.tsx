import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import {
  Wifi, RefreshCw, CheckCircle2, XCircle, AlertCircle, ChevronRight, Server,
} from "lucide-react";
import { cn } from "../lib/utils";
import { Badge } from "../components/ui/badge";

interface Step {
  name: string;
  ok: boolean;
  warn?: boolean;
  detail?: string;
}

interface CheckResult {
  label: string;
  description: string;
  ok: boolean;
  skipped?: boolean;
  warning?: boolean;
  optional?: boolean;
  error?: string;
  fa_id?: string;
  fa_name?: string;
  total_fas?: number;
  note?: string;
  steps?: Step[];
}

interface ConnectivityResult {
  overall: "ok" | "degraded";
  mode: string;
  hub_url: string;
  fa_id: string;
  fa_id_configured: boolean;
  api_key_configured: boolean;
  admin_key_configured: boolean | null;
  checks: Record<string, CheckResult>;
}

function overallVariant(check: CheckResult): "ok" | "warn" | "skip" | "error" {
  if (check.ok) return "ok";
  if (check.skipped) return "skip";
  if (check.warning) return "warn";
  return "error";
}

function StepIcon({ ok, warn }: { ok: boolean; warn?: boolean }) {
  if (ok) return <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0 mt-0.5" />;
  if (warn) return <AlertCircle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />;
  return <XCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />;
}

function StepList({ steps }: { steps: Step[] }) {
  return (
    <div className="space-y-2 pt-1">
      {steps.map((step, i) => (
        <div key={i} className="flex gap-2">
          <div className="flex items-start gap-1.5 flex-shrink-0 w-48">
            <StepIcon ok={step.ok} warn={step.warn} />
            <span className={cn(
              "text-xs font-medium leading-tight",
              step.ok ? "text-green-300" : step.warn ? "text-amber-300" : "text-red-300"
            )}>
              {step.name}
            </span>
          </div>
          {step.detail && (
            <p className="text-xs text-muted-foreground leading-tight break-words min-w-0">
              {step.detail}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

const variantStyles = {
  ok:    { border: "border-green-500/20 bg-green-500/5",   icon: CheckCircle2, iconCls: "text-green-400" },
  warn:  { border: "border-amber-500/20 bg-amber-500/5",   icon: AlertCircle,  iconCls: "text-amber-400" },
  skip:  { border: "border-zinc-700    bg-zinc-800/20",    icon: AlertCircle,  iconCls: "text-zinc-500"  },
  error: { border: "border-red-500/20  bg-red-500/10",     icon: XCircle,      iconCls: "text-red-400"   },
};

function CheckCard({ id, check }: { id: string; check: CheckResult }) {
  const variant = overallVariant(check);
  const { border, icon: Icon, iconCls } = variantStyles[variant];
  const hasDetail = (check.steps && check.steps.length > 0) || check.error;
  const [expanded, setExpanded] = useState(variant === "error" || variant === "warn");

  return (
    <div className={cn("border rounded-lg overflow-hidden", border)}>
      <button
        className={cn(
          "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors",
          hasDetail && "hover:bg-white/5 cursor-pointer"
        )}
        onClick={() => hasDetail && setExpanded(v => !v)}
        disabled={!hasDetail}
      >
        <Icon className={cn("w-5 h-5 flex-shrink-0", iconCls)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-foreground">{check.label}</span>
            {check.optional && (
              <Badge variant="outline" className="text-[9px] px-1 py-0 border-zinc-600 text-zinc-500">optional</Badge>
            )}
            {check.ok && check.fa_name && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">{check.fa_name}</Badge>
            )}
            {check.ok && check.total_fas != null && (
              <span className="text-xs text-muted-foreground">{check.total_fas} FAs registered</span>
            )}
            {check.ok && check.note && (
              <span className="text-xs text-green-400">{check.note}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 truncate">{check.description}</p>
        </div>
        {hasDetail && (
          <ChevronRight className={cn("w-4 h-4 text-muted-foreground flex-shrink-0 transition-transform", expanded && "rotate-90")} />
        )}
      </button>

      {expanded && hasDetail && (
        <div className="px-4 pb-4 pt-1 border-t border-white/5">
          {check.steps && check.steps.length > 0
            ? <StepList steps={check.steps} />
            : check.error && (
              <p className={cn("text-xs", variant === "skip" ? "text-zinc-500" : "text-red-400")}>
                {check.error}
              </p>
            )
          }
        </div>
      )}
    </div>
  );
}

export function ConnectivityPage() {
  const [result, setResult] = useState<ConnectivityResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<ConnectivityResult>("/api/connectivity/check");
      setResult(data);
      setLastChecked(new Date());
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { run(); }, [run]);

  const allOk = result?.overall === "ok";

  return (
    <div className="h-full overflow-auto bg-background">
      <div className="max-w-2xl mx-auto px-8 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Wifi className="w-6 h-6 text-muted-foreground" />
            <h1 className="text-2xl font-bold text-card-foreground">Connectivity</h1>
          </div>
          <div className="flex items-center gap-3">
            {lastChecked && (
              <span className="text-xs text-muted-foreground">Checked {lastChecked.toLocaleTimeString()}</span>
            )}
            <button
              onClick={run} disabled={loading}
              className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors disabled:opacity-50"
            >
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
              {loading ? "Checking..." : "Re-check"}
            </button>
          </div>
        </div>

        {/* Overall banner */}
        {result && (
          <div className={cn(
            "rounded-lg border px-4 py-3 flex items-center gap-3 mb-6",
            allOk ? "border-green-500/30 bg-green-500/10" : "border-amber-500/30 bg-amber-500/10"
          )}>
            {allOk
              ? <CheckCircle2 className="w-5 h-5 text-green-400 flex-shrink-0" />
              : <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0" />
            }
            <div className="flex-1 min-w-0">
              <p className={cn("text-sm font-medium", allOk ? "text-green-300" : "text-amber-300")}>
                {allOk ? "All required checks passed" : "Some checks need attention"}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                mode={result.mode} · fa={result.fa_id || "—"} · hub={result.hub_url}
              </p>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap justify-end">
              <Badge variant="outline" className={cn("text-[10px]",
                result.api_key_configured ? "border-green-500/40 text-green-400" : "border-zinc-600 text-zinc-500"
              )}>
                {result.api_key_configured ? "API key ✓" : "No API key"}
              </Badge>
              {result.admin_key_configured != null && (
                <Badge variant="outline" className={cn("text-[10px]",
                  result.admin_key_configured ? "border-green-500/40 text-green-400" : "border-amber-500/40 text-amber-400"
                )}>
                  {result.admin_key_configured ? "Admin key ✓" : "No admin key"}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Skeleton */}
        {loading && !result && (
          <div className="space-y-3">
            {[1,2,3,4].map(i => <div key={i} className="h-16 bg-muted rounded-lg animate-pulse" />)}
          </div>
        )}

        {/* Check cards */}
        {result && (
          <div className="space-y-3">
            {Object.entries(result.checks).map(([id, check]) => (
              <CheckCard key={id} id={id} check={check} />
            ))}
          </div>
        )}

        {/* Quick setup */}
        {result && !allOk && (() => {
          const cmds: { cmd: string; comment: string }[] = [];
          if (result.mode === "dev" && !result.admin_key_configured)
            cmds.push({ cmd: "make dev-init", comment: "generate local admin key, then restart backend" });
          const checks = result.checks;
          if (checks.local_hub_api && !checks.local_hub_api.ok && !checks.local_hub_api.skipped)
            cmds.push({ cmd: "cd hub-api && uvicorn hub_api.main:app --port 8000 --reload", comment: "start hub-api locally" });
          if (checks.hub_connector && !checks.hub_connector.ok && result.mode !== "dev")
            cmds.push({ cmd: "make fa-setup", comment: "start hub connector + register FA" });
          if (!result.api_key_configured && result.mode !== "dev")
            cmds.push({ cmd: "make fa-setup", comment: "configure FA API key" });
          if (cmds.length === 0) return null;
          return (
            <div className="mt-6 bg-card border border-zinc-800 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <Server className="w-4 h-4 text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Quick setup</p>
              </div>
              <div className="space-y-1.5 text-xs font-mono">
                {cmds.map(({ cmd, comment }, i) => (
                  <p key={i}>
                    <span className="text-zinc-500">$ </span>
                    <span className="text-zinc-200">{cmd}</span>
                    <span className="text-zinc-600 ml-2"># {comment}</span>
                  </p>
                ))}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
