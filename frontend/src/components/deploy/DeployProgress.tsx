import { useEffect, useState, useRef, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CheckCircle, XCircle, AlertTriangle, Loader2, Terminal } from "lucide-react";
import { useDebugStore } from "../../stores/debugStore";
import { apiFetch } from "../../api/client";
import { apiUrl } from "../../lib/apiBase";

interface DeployStep {
  step: string;
  status: "running" | "done" | "error" | "warning";
  detail: string;
}

const STEP_LABELS: Record<string, string> = {
  compose: "Generate Compose",
  cleanup: "Cleanup Previous",
  containers: "Start Containers",
  networks: "Connect Networks",
  discovery: "Discover Containers",
  init_scripts: "Integration Scripts",
  edge_config: "Configure Connections",
  complete: "Complete",
  rollback: "Rollback",
  error: "Error",
};

interface Props {
  demoId: string;
  demoName: string;
  onDone: (success: boolean) => void;
  taskId?: string;
}

export default function DeployProgress({ demoId, demoName, onDone, taskId }: Props) {
  const [steps, setSteps] = useState<DeployStep[]>([]);
  const [finished, setFinished] = useState<boolean | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const addEntry = useDebugStore((s) => s.addEntry);
  const prevStepStatuses = useRef<Record<string, string>>({});
  const lastHeartbeat = useRef<Record<string, number>>({});
  const [initLogs, setInitLogs] = useState<string[] | null>(null);
  const [initLogsLoading, setInitLogsLoading] = useState(false);
  // Guard: ensure onDone fires exactly once regardless of how many paths reach it
  const calledRef = useRef(false);
  const safeOnDone = (success: boolean) => {
    if (calledRef.current) return;
    calledRef.current = true;
    onDone(success);
  };

  const loadInitLogs = useCallback(async () => {
    setInitLogsLoading(true);
    try {
      const data = await apiFetch<{ lines: string[] }>(`/api/demos/${demoId}/instances/metabase-init/logs?tail=100`);
      setInitLogs(data.lines ?? []);
    } catch {
      setInitLogs(["(could not fetch init logs)"]);
    } finally {
      setInitLogsLoading(false);
    }
  }, [demoId]);

  useEffect(() => {
    const poll = async () => {
      try {
        // Prefer task endpoint when taskId is available
        const url = taskId
          ? apiUrl(`/api/demos/${demoId}/task/${taskId}`)
          : apiUrl(`/api/demos/${demoId}/deploy/progress`);
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        if (data.steps && data.steps.length > 0) {
          setSteps(data.steps);
          for (const s of data.steps as DeployStep[]) {
            const prev = prevStepStatuses.current[s.step];
            if (prev !== s.status) {
              prevStepStatuses.current[s.step] = s.status;
              const source = s.step === "init_scripts" ? "Provision" : "Deploy";
              if (s.status === "done" || s.status === "error" || s.status === "warning") {
                const level = s.status === "error" ? "error" : s.status === "warning" ? "warn" : "info";
                const label = STEP_LABELS[s.step] ?? s.step;
                addEntry(level, source, `${label}: ${s.status}`, s.detail || undefined);
              } else if (s.status === "running" && !prev) {
                addEntry("info", source, `${STEP_LABELS[s.step] ?? s.step}: started`, s.detail || undefined);
                lastHeartbeat.current[s.step] = Date.now();
              }
              // Heartbeat: log every 8s while a step stays in "running"
              if (s.status === "running") {
                const last = lastHeartbeat.current[s.step] ?? 0;
                if (Date.now() - last >= 8000) {
                  lastHeartbeat.current[s.step] = Date.now();
                  addEntry("info", source, `${STEP_LABELS[s.step] ?? s.step}: still running\u2026`, s.detail || undefined);
                }
              }
            }
          }
        }
        if (data.finished) {
          const hasError = data.steps.some((s: DeployStep) => s.step === "error" || s.step === "rollback");
          const isComplete = data.steps.some((s: DeployStep) => s.step === "complete");
          const success = hasError ? false : isComplete ? true : true;
          setFinished(success);
          if (intervalRef.current) clearInterval(intervalRef.current);
          // Auto-dismiss on success — only keep modal open on error
          if (success) {
            setTimeout(() => safeOnDone(true), 500);
          }
        }
      } catch {}
    };

    // Poll every 500ms
    poll();
    intervalRef.current = setInterval(poll, 500);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [demoId, taskId]);

  const statusIcon = (status: string) => {
    switch (status) {
      case "running":
        return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />;
      case "done":
        return <CheckCircle className="w-4 h-4 text-green-400" />;
      case "error":
        return <XCircle className="w-4 h-4 text-red-400" />;
      case "warning":
        return <AlertTriangle className="w-4 h-4 text-yellow-400" />;
      default:
        return <span className="inline-block w-4 h-4 rounded-full bg-zinc-600" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <Card className="w-[420px] max-h-[80vh] overflow-auto">
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-semibold text-foreground">Deploying "{demoName}"</h3>
              <p className="text-xs text-muted-foreground mt-0.5">{demoId}</p>
            </div>
            {finished === null ? (
              <span className="inline-block w-5 h-5 rounded-full border-2 border-primary border-t-transparent animate-spin" />
            ) : (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground"
                onClick={() => safeOnDone(finished)}
              >
                <XCircle className="h-4 w-4" />
              </Button>
            )}
          </div>

          <div className="space-y-1">
            {steps.map((s) => (
              <div key={s.step}>
                <div
                  className={`flex items-start gap-3 px-3 py-2 rounded-md transition-colors ${
                    s.status === "running" ? "bg-blue-500/5" :
                    s.status === "error" ? "bg-red-500/5" :
                    s.status === "warning" ? "bg-yellow-500/5" :
                    "bg-transparent"
                  }`}
                >
                  <div className="mt-0.5 flex-shrink-0">{statusIcon(s.status)}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground">
                        {STEP_LABELS[s.step] ?? s.step}
                      </span>
                      {s.step === "init_scripts" && (s.status === "done" || s.status === "error" || s.status === "warning") && (
                        <button
                          className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-200 transition-colors"
                          onClick={() => initLogs === null ? loadInitLogs() : setInitLogs(null)}
                        >
                          <Terminal className="w-3 h-3" />
                          {initLogs !== null ? "hide" : "view logs"}
                        </button>
                      )}
                    </div>
                    {s.detail && (
                      <div className={`text-xs mt-0.5 ${
                        s.status === "error" ? "text-red-400" :
                        s.status === "warning" ? "text-yellow-400" :
                        "text-muted-foreground"
                      } break-all`}>
                        {s.detail}
                      </div>
                    )}
                  </div>
                </div>
                {s.step === "init_scripts" && initLogs !== null && (
                  <div className="mx-3 mb-1 rounded border border-zinc-700 bg-zinc-900 p-2 max-h-40 overflow-auto">
                    {initLogsLoading ? (
                      <p className="text-xs text-zinc-500">Loading...</p>
                    ) : initLogs.length === 0 ? (
                      <p className="text-xs text-zinc-500">No log output yet.</p>
                    ) : (
                      <pre className="text-[10px] text-zinc-300 whitespace-pre-wrap break-all leading-relaxed">
                        {initLogs.join("\n")}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          {steps.length === 0 && finished === null && (
            <div className="text-center py-6 text-sm text-muted-foreground">
              Starting deployment...
            </div>
          )}

          <div className="mt-4 pt-3 border-t border-border flex items-center justify-between">
            {finished !== null ? (
              <>
                <span className={`text-sm font-medium ${finished ? "text-green-400" : "text-red-400"}`}>
                  {finished ? "Deployment successful" : "Deployment failed"}
                </span>
                <Button size="sm" variant={finished ? "default" : "destructive"} onClick={() => safeOnDone(finished)}>
                  {finished ? "Done" : "Close"}
                </Button>
              </>
            ) : (
              <>
                <span className="text-xs text-muted-foreground">Deploy in progress...</span>
                <Button size="sm" variant="ghost" onClick={() => safeOnDone(true)} className="text-xs text-muted-foreground">
                  Dismiss
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
