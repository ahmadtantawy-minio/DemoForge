import { useEffect, useRef, useState } from "react";
import { execCommand } from "../../api/client";

interface RagAppPanelProps {
  nodeId: string;
  demoId: string | null;
  isRunning: boolean;
}

export function RagAppPanel({ nodeId, demoId, isRunning }: RagAppPanelProps) {
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
        const healthRes = await execCommand(demoId, nodeId, "wget -qO- http://localhost:8080/health 2>/dev/null");
        const statusRes = await execCommand(demoId, nodeId, "wget -qO- http://localhost:8080/status 2>/dev/null");
        const health = healthRes.exit_code === 0 ? JSON.parse(healthRes.stdout) : {};
        const status = statusRes.exit_code === 0 ? JSON.parse(statusRes.stdout) : {};
        setRagStatus({ ...health, ...status });
      } catch {}
    };
    poll();
    pollRef.current = setInterval(poll, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isRunning, demoId, nodeId]);

  const handleIngestSample = async () => {
    if (!demoId) return;
    await execCommand(demoId, nodeId, "wget -qO- --post-data='' http://localhost:8080/ingest/sample 2>/dev/null");
  };

  const handleAskTest = async () => {
    if (!demoId) return;
    await execCommand(
      demoId,
      nodeId,
      'wget -qO- --post-data=\'{"question":"What is MinIO?"}\' --header=\'Content-Type: application/json\' http://localhost:8080/ask 2>/dev/null'
    );
  };

  const handleReset = async () => {
    if (!demoId) return;
    await execCommand(demoId, nodeId, "wget -qO- --method=DELETE http://localhost:8080/collection 2>/dev/null");
  };

  return (
    <div className="mt-3 pt-3 border-t border-border space-y-3">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">RAG Pipeline</div>

      {ragStatus && (
        <>
          <div className="space-y-1 text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.minio_connected ? "bg-green-500" : "bg-red-500"}`} />
              MinIO
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.qdrant_connected ? "bg-green-500" : "bg-red-500"}`} />
              Qdrant
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.models_loaded ? "bg-green-500" : "bg-yellow-400 animate-pulse"}`} />
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
          <button
            type="button"
            onClick={handleIngestSample}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted transition-colors"
          >
            Load sample docs
          </button>
          <button
            type="button"
            onClick={handleAskTest}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted transition-colors"
          >
            Ask test question
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted transition-colors text-destructive"
          >
            Reset collection
          </button>
        </div>
      )}
    </div>
  );
}
