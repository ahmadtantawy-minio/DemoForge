import { useEffect, useState } from "react";
import { fetchSparkEtlJobPreview } from "@/api/client";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
  nodeId: string;
};

export default function SparkJobCodeDialog({ open, onOpenChange, demoId, nodeId }: Props) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchSparkEtlJobPreview>> | null>(null);

  useEffect(() => {
    if (!open || !demoId || !nodeId) return;
    setLoading(true);
    setErr(null);
    fetchSparkEtlJobPreview(demoId, nodeId)
      .then(setData)
      .catch((e: Error) => setErr(e.message || String(e)))
      .finally(() => setLoading(false));
  }, [open, demoId, nodeId]);

  const scheduleNote =
    data?.job_schedule === "manual"
      ? "JOB_SCHEDULE=manual: the container stays idle until you run spark-submit yourself (Open Terminal). No automatic run history."
      : data?.job_schedule === "interval"
        ? "JOB_SCHEDULE=interval: spark-submit repeats every JOB_INTERVAL_SEC; each run is logged below in Run history."
        : "JOB_SCHEDULE=on_deploy_once: one spark-submit at container start, then the process stays up for logs.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col gap-2">
        <DialogHeader>
          <DialogTitle>Apache Spark job — {nodeId}</DialogTitle>
          <DialogDescription className="text-xs">
            Driver script and effective runtime (from compose generation). Secrets are redacted.
          </DialogDescription>
        </DialogHeader>
        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {err && (
          <p className="text-sm text-destructive whitespace-pre-wrap break-words">{err}</p>
        )}
        {data && !err && (
          <>
            <p className="text-xs text-muted-foreground border border-border rounded-md px-2 py-1.5">{scheduleNote}</p>
            <Tabs defaultValue="script" className="flex-1 min-h-0 flex flex-col">
              <TabsList className="w-fit">
                <TabsTrigger value="script">PySpark ({data.job_script_path})</TabsTrigger>
                <TabsTrigger value="cmd">spark-submit</TabsTrigger>
                <TabsTrigger value="env">Environment</TabsTrigger>
              </TabsList>
              <TabsContent value="script" className="flex-1 min-h-0 mt-2 data-[state=inactive]:hidden">
                <pre className="text-xs font-mono bg-muted/40 rounded-md p-3 overflow-auto max-h-[50vh] whitespace-pre">
                  {data.job_script}
                </pre>
              </TabsContent>
              <TabsContent value="cmd" className="flex-1 min-h-0 mt-2 data-[state=inactive]:hidden">
                <pre className="text-xs font-mono bg-muted/40 rounded-md p-3 overflow-auto max-h-[40vh] whitespace-pre">
                  {data.spark_submit_command}
                </pre>
              </TabsContent>
              <TabsContent value="env" className="flex-1 min-h-0 mt-2 data-[state=inactive]:hidden">
                <pre className="text-xs font-mono bg-muted/40 rounded-md p-3 overflow-auto max-h-[50vh] whitespace-pre">
                  {Object.entries(data.environment)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([k, v]) => `${k}=${v}`)
                    .join("\n")}
                </pre>
              </TabsContent>
            </Tabs>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
