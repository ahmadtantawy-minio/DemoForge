import { useState, useEffect } from "react";
import { fetchPlaybook, executeSql } from "../../api/client";
import { Play, Check, X, Loader2, Copy, ChevronDown, ChevronRight } from "lucide-react";

interface PlaybookStep {
  step: number;
  title: string;
  description: string;
  sql: string;
  expected: string;
}

interface StepState {
  status: "pending" | "running" | "success" | "error";
  result?: { columns: { name: string; type: string }[]; rows: any[][]; row_count: number; execution_time_ms: number };
  error?: string;
}

export default function SqlPlaybookPanel({ demoId }: { demoId: string }) {
  const [steps, setSteps] = useState<PlaybookStep[]>([]);
  const [scenarioName, setScenarioName] = useState("");
  const [stepStates, setStepStates] = useState<Record<number, StepState>>({});
  const [expandedStep, setExpandedStep] = useState<number>(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    fetchPlaybook(demoId)
      .then((data) => {
        setSteps(data.steps);
        setScenarioName(data.scenario_name);
        if (data.steps.length > 0) setExpandedStep(data.steps[0].step);
      })
      .catch((e) => setError(e.message || "Failed to load playbook"))
      .finally(() => setLoading(false));
  }, [demoId]);

  async function runStep(step: PlaybookStep) {
    setStepStates((prev) => ({ ...prev, [step.step]: { status: "running" } }));
    try {
      const result = await executeSql(demoId, step.sql);
      setStepStates((prev) => ({
        ...prev,
        [step.step]: {
          status: result.success ? "success" : "error",
          result: result.success ? result : undefined,
          error: result.error || undefined,
        },
      }));
      if (result.success) setExpandedStep(step.step + 1);
    } catch (e: any) {
      setStepStates((prev) => ({
        ...prev,
        [step.step]: { status: "error", error: String(e) },
      }));
    }
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground gap-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-xs">Loading playbook…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-xs text-muted-foreground text-center py-8">
        {error}
      </div>
    );
  }

  if (steps.length === 0) return null;

  return (
    <div className="space-y-2 p-3" data-testid="sql-playbook-panel">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
        SQL Playbook — {scenarioName}
      </div>

      {steps.map((step) => {
        const state = stepStates[step.step] || { status: "pending" as const };
        const isExpanded = expandedStep === step.step;

        return (
          <div
            key={step.step}
            className={`border rounded-lg transition-all ${
              state.status === "success"
                ? "border-green-500/30 bg-green-500/5"
                : state.status === "error"
                ? "border-red-500/30 bg-red-500/5"
                : state.status === "running"
                ? "border-primary/30 bg-primary/5"
                : "border-border"
            }`}
            data-testid={`playbook-step-${step.step}`}
            data-expanded={isExpanded}
          >
            {/* Step header */}
            <button
              className="w-full flex items-center gap-2 p-2.5 text-left"
              onClick={() => setExpandedStep(isExpanded ? -1 : step.step)}
            >
              <div className="flex-shrink-0">
                {state.status === "success" ? (
                  <Check className="w-4 h-4 text-green-500" />
                ) : state.status === "error" ? (
                  <X className="w-4 h-4 text-red-500" />
                ) : state.status === "running" ? (
                  <Loader2 className="w-4 h-4 text-primary animate-spin" />
                ) : (
                  <div className="w-4 h-4 rounded-full border-2 border-muted-foreground/30 flex items-center justify-center text-[9px] font-bold text-muted-foreground">
                    {step.step}
                  </div>
                )}
              </div>
              <span className="text-xs font-medium flex-1">{step.title}</span>
              <span className="text-[10px] text-muted-foreground" data-testid={`playbook-step-${step.step}-status`}>
                {state.status}
              </span>
              {isExpanded ? (
                <ChevronDown className="w-3 h-3 text-muted-foreground" />
              ) : (
                <ChevronRight className="w-3 h-3 text-muted-foreground" />
              )}
            </button>

            {/* Expanded content */}
            {isExpanded && (
              <div className="px-2.5 pb-2.5 space-y-2">
                {step.description && (
                  <p className="text-[11px] text-muted-foreground">{step.description}</p>
                )}

                {/* SQL block */}
                <div className="relative group" data-testid={`playbook-sql-${step.step}`}>
                  <pre className="text-[10px] bg-black/20 rounded p-2 overflow-x-auto text-foreground/80 font-mono whitespace-pre-wrap">
                    {step.sql.trim()}
                  </pre>
                  <button
                    className="absolute top-1 right-1 p-1 rounded bg-background/80 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={(e) => { e.stopPropagation(); copyToClipboard(step.sql); }}
                    title="Copy SQL"
                    data-testid={`playbook-copy-${step.step}`}
                  >
                    <Copy className="w-3 h-3" />
                  </button>
                </div>

                {/* Run button */}
                <div className="flex items-center justify-between">
                  {step.expected && (
                    <span className="text-[10px] text-muted-foreground italic">{step.expected}</span>
                  )}
                  <button
                    className={`ml-auto flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-all ${
                      state.status === "running"
                        ? "bg-primary/20 text-primary cursor-wait"
                        : "bg-primary text-primary-foreground hover:bg-primary/90"
                    }`}
                    onClick={(e) => { e.stopPropagation(); runStep(step); }}
                    disabled={state.status === "running"}
                    data-testid={`playbook-run-${step.step}`}
                  >
                    {state.status === "running" ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Play className="w-3 h-3" />
                    )}
                    {state.status === "running" ? "Running…" : "Run"}
                  </button>
                </div>

                {/* Results */}
                {state.status === "success" && state.result && (
                  <div className="space-y-1" data-testid={`playbook-step-${step.step}-result`}>
                    <div className="text-[10px] text-green-500 font-medium">
                      {state.result.row_count} row{state.result.row_count !== 1 ? "s" : ""} · {state.result.execution_time_ms}ms
                    </div>
                    {state.result.rows.length > 0 && (
                      <div className="overflow-x-auto max-h-48">
                        <table className="text-[10px] w-full">
                          <thead>
                            <tr className="border-b border-border">
                              {state.result.columns.map((col) => (
                                <th key={col.name} className="text-left px-1.5 py-1 text-muted-foreground font-medium whitespace-nowrap">
                                  {col.name}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {state.result.rows.slice(0, 20).map((row, i) => (
                              <tr key={i} className="border-b border-border/50">
                                {row.map((cell, j) => (
                                  <td key={j} className="px-1.5 py-0.5 whitespace-nowrap max-w-[150px] truncate">
                                    {cell == null ? <span className="text-muted-foreground">null</span> : String(cell)}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {state.result.rows.length > 20 && (
                          <div className="text-[9px] text-muted-foreground text-center py-1">
                            Showing 20 of {state.result.row_count} rows
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Error */}
                {state.status === "error" && state.error && (
                  <div className="text-[10px] text-red-400 bg-red-500/10 rounded p-2">
                    {state.error}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
