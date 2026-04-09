import { useEffect, useState, useRef } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CheckCircle, XCircle, AlertTriangle, Loader2 } from "lucide-react";

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
  init_scripts: "Init Scripts",
  edge_config: "Configure Connections",
  complete: "Complete",
  rollback: "Rollback",
  error: "Error",
};

interface Props {
  demoId: string;
  demoName: string;
  apiBase: string;
  onDone: (success: boolean) => void;
  taskId?: string;
}

export default function DeployProgress({ demoId, demoName, apiBase, onDone, taskId }: Props) {
  const [steps, setSteps] = useState<DeployStep[]>([]);
  const [finished, setFinished] = useState<boolean | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Guard: ensure onDone fires exactly once regardless of how many paths reach it
  const calledRef = useRef(false);
  const safeOnDone = (success: boolean) => {
    if (calledRef.current) return;
    calledRef.current = true;
    onDone(success);
  };

  useEffect(() => {
    const poll = async () => {
      try {
        // Prefer task endpoint when taskId is available
        const url = taskId
          ? `${apiBase}/api/demos/${demoId}/task/${taskId}`
          : `${apiBase}/api/demos/${demoId}/deploy/progress`;
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        if (data.steps && data.steps.length > 0) {
          setSteps(data.steps);
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
  }, [demoId, apiBase, taskId]);

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
              <div
                key={s.step}
                className={`flex items-start gap-3 px-3 py-2 rounded-md transition-colors ${
                  s.status === "running" ? "bg-blue-500/5" :
                  s.status === "error" ? "bg-red-500/5" :
                  s.status === "warning" ? "bg-yellow-500/5" :
                  "bg-transparent"
                }`}
              >
                <div className="mt-0.5 flex-shrink-0">{statusIcon(s.status)}</div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">
                    {STEP_LABELS[s.step] ?? s.step}
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
