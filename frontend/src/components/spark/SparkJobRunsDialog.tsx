import { useCallback, useEffect, useState } from "react";
import { fetchSparkEtlJobRuns } from "@/api/client";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
  nodeId: string;
  onViewContainerLogs?: () => void;
};

export default function SparkJobRunsDialog({
  open,
  onOpenChange,
  demoId,
  nodeId,
  onViewContainerLogs,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [payload, setPayload] = useState<Awaited<ReturnType<typeof fetchSparkEtlJobRuns>> | null>(null);

  const load = useCallback(() => {
    if (!demoId || !nodeId) return;
    setLoading(true);
    setErr(null);
    fetchSparkEtlJobRuns(demoId, nodeId)
      .then(setPayload)
      .catch((e: Error) => setErr(e.message || String(e)))
      .finally(() => setLoading(false));
  }, [demoId, nodeId]);

  useEffect(() => {
    if (!open) return;
    load();
  }, [open, load]);

  const runs = payload?.runs ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col gap-2">
        <DialogHeader>
          <DialogTitle>Run history — {nodeId}</DialogTitle>
          <DialogDescription className="text-xs">
            One line per event in {payload?.log_path ?? "/tmp/demoforge-spark-runs.ndjson"}:{" "}
            <strong>submitted</strong> when spark-submit begins, then <strong>ok</strong> / <strong>error</strong> on
            spark_submit_finished (exit code). Older logs may show running on start rows — same meaning.
            For driver/executor output, open container logs.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
            Refresh
          </Button>
          {onViewContainerLogs && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => {
                onViewContainerLogs();
                onOpenChange(false);
              }}
            >
              View container logs
            </Button>
          )}
        </div>
        {loading && !payload && <p className="text-sm text-muted-foreground">Loading…</p>}
        {err && <p className="text-sm text-destructive whitespace-pre-wrap break-words">{err}</p>}
        {payload?.message && !err && (
          <p className="text-xs text-amber-600 dark:text-amber-400 border border-border rounded-md px-2 py-1.5">
            {payload.message}
          </p>
        )}
        {payload &&
          !err &&
          payload.last_finished_success === false &&
          payload.last_finished_exit_code != null && (
            <p className="text-xs text-red-600 dark:text-red-400 border border-red-500/30 bg-red-500/5 rounded-md px-2 py-1.5">
              Last spark-submit failed (exit {payload.last_finished_exit_code}). See container logs for the Java /
              Python stack trace.
            </p>
          )}
        {payload &&
          !err &&
          payload.last_finished_success === true &&
          payload.last_finished_exit_code != null && (
            <p className="text-xs text-emerald-700 dark:text-emerald-400/90 border border-emerald-500/25 bg-emerald-500/5 rounded-md px-2 py-1.5">
              Last spark-submit succeeded (exit {payload.last_finished_exit_code}).
            </p>
          )}
        {payload?.submit_log_tail && !err && (
          <div className="border border-border rounded-md overflow-hidden">
            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide px-2 py-1 bg-muted/50 border-b border-border">
              Last spark-submit output
            </div>
            <pre className="text-[11px] font-mono p-2 max-h-48 overflow-auto whitespace-pre-wrap break-words text-foreground/90">
              {payload.submit_log_tail}
            </pre>
          </div>
        )}
        {payload && !err && (
          <div className="border border-border rounded-md overflow-auto max-h-[55vh]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                <tr className="text-left border-b border-border">
                  <th className="p-2 font-medium">Time (UTC)</th>
                  <th className="p-2 font-medium">Phase</th>
                  <th className="p-2 font-medium">Schedule</th>
                  <th className="p-2 font-medium">Status</th>
                  <th className="p-2 font-medium">Exit</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="p-3 text-muted-foreground">
                      No run records yet. Deploy the demo, or wait for the next interval run.
                    </td>
                  </tr>
                ) : (
                  runs.map((r, i) => {
                    const stRaw = (r.status || "").toLowerCase();
                    // Legacy NDJSON used "running" on spark_submit_start; those rows are never updated (append-only log).
                    const st =
                      r.phase === "spark_submit_start" && stRaw === "running" ? "submitted" : stRaw;
                    const errRow = st === "error" || r.success === false;
                    const okRow = st === "ok" || r.success === true;
                    const submittedRow = st === "submitted";
                    const statusLabel =
                      (r.phase === "spark_submit_start" && stRaw === "running" ? "submitted" : r.status) ||
                      (r.phase === "spark_submit_finished" && r.exit_code != null
                        ? r.exit_code === 0
                          ? "ok"
                          : "error"
                        : "—");
                    return (
                      <tr
                        key={`${r.ts}-${r.phase}-${i}`}
                        className={`border-b border-border/60 hover:bg-muted/30 ${errRow ? "bg-red-500/5" : okRow ? "bg-emerald-500/5" : ""}`}
                      >
                        <td className="p-2 font-mono whitespace-nowrap">{r.ts || "—"}</td>
                        <td className="p-2 font-mono">{r.phase || "—"}</td>
                        <td className="p-2">{r.schedule || "—"}</td>
                        <td className="p-2">
                          <span
                            className={
                              errRow
                                ? "text-red-600 dark:text-red-400 font-medium"
                                : okRow
                                  ? "text-emerald-600 dark:text-emerald-400/90 font-medium"
                                  : submittedRow
                                    ? "text-sky-600 dark:text-sky-400/90"
                                    : "text-muted-foreground"
                            }
                          >
                            {statusLabel}
                          </span>
                        </td>
                        <td className="p-2 font-mono">
                          {r.exit_code === null || r.exit_code === undefined ? "—" : String(r.exit_code)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
