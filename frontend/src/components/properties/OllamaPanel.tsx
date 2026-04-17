import { useEffect, useRef, useState } from "react";
import { execCommand } from "../../api/client";

interface OllamaPanelProps {
  nodeId: string;
  demoId: string | null;
  isRunning: boolean;
}

export function OllamaPanel({ nodeId, demoId, isRunning }: OllamaPanelProps) {
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
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
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
