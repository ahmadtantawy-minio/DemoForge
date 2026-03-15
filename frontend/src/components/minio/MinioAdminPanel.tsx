import { useState, useEffect, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface BucketInfo {
  name: string;
  policy: string;
  versioning: string;
}

interface ClusterInfo {
  cluster_id: string;
  alias: string;
  server_info: string;
  buckets: BucketInfo[];
  users: string;
  site_replication: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clusterId: string;
  clusterLabel: string;
}

export default function MinioAdminPanel({ open, onOpenChange, clusterId, clusterLabel }: Props) {
  const { activeDemoId } = useDemoStore();
  const [info, setInfo] = useState<ClusterInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [mcCommand, setMcCommand] = useState("");
  const [mcOutput, setMcOutput] = useState("");
  const [mcRunning, setMcRunning] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "buckets" | "users" | "mc">("overview");

  const fetchInfo = useCallback(async () => {
    if (!activeDemoId || !clusterId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/minio/${clusterId}/info`);
      if (res.ok) {
        setInfo(await res.json());
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [activeDemoId, clusterId]);

  useEffect(() => {
    if (open) fetchInfo();
  }, [open, fetchInfo]);

  const runMcCommand = async () => {
    if (!activeDemoId || !clusterId || !mcCommand.trim()) return;
    setMcRunning(true);
    setMcOutput("");
    try {
      const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/minio/${clusterId}/mc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: mcCommand }),
      });
      const data = await res.json();
      const output = `$ ${data.command}\n${data.stdout || ""}${data.stderr ? `\n${data.stderr}` : ""}`;
      setMcOutput((prev) => (prev ? prev + "\n\n" : "") + output);
      if (data.exit_code !== 0) {
        toast.error("Command failed", { description: data.stderr?.substring(0, 100) });
      }
    } catch (e: any) {
      setMcOutput((prev) => prev + `\nError: ${e.message}`);
    }
    setMcRunning(false);
  };

  const setBucketPolicy = async (bucket: string, policy: string) => {
    if (!activeDemoId) return;
    try {
      const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/minio/${clusterId}/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bucket, policy }),
      });
      if (res.ok) {
        toast.success(`Policy set to '${policy}' for ${bucket}`);
        fetchInfo();
      } else {
        const err = await res.json();
        toast.error("Failed", { description: err.detail || err.message });
      }
    } catch (e: any) {
      toast.error("Failed", { description: e.message });
    }
  };

  const toggleVersioning = async (bucket: string, enabled: boolean) => {
    if (!activeDemoId) return;
    try {
      const res = await fetch(`${API_BASE}/api/demos/${activeDemoId}/minio/${clusterId}/versioning`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bucket, enabled }),
      });
      if (res.ok) {
        toast.success(`Versioning ${enabled ? "enabled" : "suspended"} for ${bucket}`);
        fetchInfo();
      } else {
        const err = await res.json();
        toast.error("Failed", { description: err.detail || err.message });
      }
    } catch (e: any) {
      toast.error("Failed", { description: e.message });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">MinIO Admin — {clusterLabel}</DialogTitle>
        </DialogHeader>

        {/* Tab bar */}
        <div className="flex gap-1 border-b border-border pb-1">
          {(["overview", "buckets", "users", "mc"] as const).map((tab) => (
            <button
              key={tab}
              className={`px-3 py-1 text-xs rounded-t ${activeTab === tab
                ? "bg-card text-foreground border border-b-0 border-border"
                : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab === "mc" ? "mc Console" : tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
          <button
            className="ml-auto px-2 py-1 text-[10px] text-muted-foreground hover:text-foreground"
            onClick={fetchInfo}
            disabled={loading}
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 pt-2">
          {/* Overview tab */}
          {activeTab === "overview" && info && (
            <pre className="text-xs font-mono whitespace-pre-wrap text-muted-foreground bg-muted/30 rounded p-3 max-h-[50vh] overflow-y-auto">
              {info.server_info}
              {"\n\n--- Site Replication ---\n"}
              {info.site_replication}
            </pre>
          )}

          {/* Buckets tab */}
          {activeTab === "buckets" && info && (
            <div className="space-y-2">
              {info.buckets.length === 0 && (
                <div className="text-xs text-muted-foreground p-3">No buckets found</div>
              )}
              {info.buckets.map((b) => (
                <div key={b.name} className="border border-border rounded p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-foreground">{b.name}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      b.versioning === "enabled" ? "bg-green-500/10 text-green-400" :
                      b.versioning === "suspended" ? "bg-yellow-500/10 text-yellow-400" :
                      "bg-muted text-muted-foreground"
                    }`}>
                      {b.versioning}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Policy:</span>
                    <Select
                      value={b.policy === "custom" ? "custom" : b.policy}
                      onValueChange={(v) => { if (v !== "custom") setBucketPolicy(b.name, v); }}
                    >
                      <SelectTrigger className="h-7 text-xs w-28">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">None</SelectItem>
                        <SelectItem value="public">Public</SelectItem>
                        <SelectItem value="download">Download</SelectItem>
                        <SelectItem value="upload">Upload</SelectItem>
                        {b.policy === "custom" && <SelectItem value="custom">Custom</SelectItem>}
                      </SelectContent>
                    </Select>
                    <span className="text-xs text-muted-foreground ml-2">Versioning:</span>
                    <Button
                      size="sm"
                      variant={b.versioning === "enabled" ? "default" : "outline"}
                      className="h-6 text-[10px] px-2"
                      onClick={() => toggleVersioning(b.name, b.versioning !== "enabled")}
                    >
                      {b.versioning === "enabled" ? "Enabled" : "Enable"}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Users tab */}
          {activeTab === "users" && info && (
            <pre className="text-xs font-mono whitespace-pre-wrap text-muted-foreground bg-muted/30 rounded p-3 max-h-[50vh] overflow-y-auto">
              {info.users || "No users configured"}
            </pre>
          )}

          {/* mc Console tab */}
          {activeTab === "mc" && (
            <div className="flex flex-col h-full">
              <div className="text-[10px] text-muted-foreground mb-1">
                Run mc commands against <span className="text-foreground font-medium">{info?.alias || clusterId}</span>.
                The alias is auto-injected.
              </div>
              <div className="flex gap-1 mb-2">
                <Input
                  value={mcCommand}
                  onChange={(e) => setMcCommand(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") runMcCommand(); }}
                  placeholder="e.g. ls, admin info, admin user ls, version info BUCKET"
                  className="h-8 text-xs font-mono flex-1"
                  disabled={mcRunning}
                />
                <Button size="sm" className="h-8 text-xs px-3" onClick={runMcCommand} disabled={mcRunning || !mcCommand.trim()}>
                  {mcRunning ? "..." : "Run"}
                </Button>
                <Button size="sm" variant="outline" className="h-8 text-xs px-2" onClick={() => setMcOutput("")}>
                  Clear
                </Button>
              </div>
              <pre className="text-xs font-mono whitespace-pre-wrap text-green-400 bg-zinc-950 rounded p-3 flex-1 min-h-[200px] max-h-[40vh] overflow-y-auto border border-border">
                {mcOutput || "# Output will appear here\n# Try: ls, admin info, admin user ls, version info demo-bucket"}
              </pre>
              <div className="flex gap-1 mt-2 flex-wrap">
                {["ls", "admin info", "admin user ls", "admin replicate info", "admin tier ls"].map((cmd) => (
                  <button
                    key={cmd}
                    className="px-2 py-0.5 text-[10px] bg-muted rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                    onClick={() => { setMcCommand(cmd); }}
                  >
                    {cmd}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!info && !loading && (
            <div className="text-xs text-muted-foreground p-3">No data available. Click Refresh.</div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
