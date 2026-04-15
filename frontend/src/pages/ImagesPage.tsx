import { useEffect, useState, useCallback } from "react";
import { getImageStatus, pullImage, getPullStatus, pullAllMissing, getDanglingImages, pruneDanglingImages, ImageInfo } from "../api/images";
import { hubPushImages } from "../api/client";
import { ImageStatusBadge } from "../components/images/ImageStatusBadge";
import { RefreshCw, Download, Cloud, CloudOff, HardDrive, Server, Upload } from "lucide-react";
import { toast } from "../lib/toast";
import { useDemoStore } from "../stores/demoStore";

type ImageWithPull = ImageInfo & { pullStatus?: "pulling" | "complete" | "error"; pullPct?: number };

export function ImagesPage() {
  const { faMode } = useDemoStore();
  const [images, setImages] = useState<ImageWithPull[]>([]);
  const [loading, setLoading] = useState(true);
  const [pullingAll, setPullingAll] = useState(false);
  const [hubPushing, setHubPushing] = useState(false);
  const [dangling, setDangling] = useState<{ count: number; reclaimable_mb: number } | null>(null);
  const [pruning, setPruning] = useState(false);
  const [registryStatus, setRegistryStatus] = useState<"checking" | "connected" | "unreachable" | "not_configured">("checking");

  const loadImages = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getImageStatus();
      setImages(data.map(i => ({ ...i })));
    } catch {} finally {
      setLoading(false);
    }
    getDanglingImages().then(setDangling).catch(() => {});
  }, []);

  useEffect(() => { loadImages(); }, [loadImages]);

  // Check if private registry is reachable (via backend)
  const [registryHost, setRegistryHost] = useState("");
  useEffect(() => {
    setRegistryStatus("checking");
    fetch(`${import.meta.env.VITE_API_URL || "http://localhost:9210"}/api/images/registry-health`)
      .then(r => r.json())
      .then(d => {
        setRegistryHost(d.host || "");
        if (d.status === "connected") setRegistryStatus("connected");
        else if (d.status === "not_configured") setRegistryStatus("not_configured");
        else setRegistryStatus("unreachable");
      })
      .catch(() => setRegistryStatus("unreachable"));
  }, []);

  const handlePull = async (imageRef: string) => {
    try {
      const { pull_id } = await pullImage(imageRef);
      setImages(prev => prev.map(i => i.image_ref === imageRef ? { ...i, pullStatus: "pulling", pullPct: 0 } : i));

      // Poll until done
      const poll = setInterval(async () => {
        try {
          const status = await getPullStatus(pull_id);
          if (status.status === "complete") {
            clearInterval(poll);
            setImages(prev => prev.map(i => i.image_ref === imageRef ? { ...i, cached: true, status: "cached", pullStatus: "complete" } : i));
            toast.success(`Pulled ${imageRef}`);
          } else if (status.status === "error") {
            clearInterval(poll);
            setImages(prev => prev.map(i => i.image_ref === imageRef ? { ...i, pullStatus: "error" } : i));
            toast.error(`Failed to pull ${imageRef}`, { description: status.error || "Unknown error" });
          } else {
            setImages(prev => prev.map(i => i.image_ref === imageRef ? { ...i, pullPct: status.progress_pct || 0 } : i));
          }
        } catch { clearInterval(poll); }
      }, 2000);
    } catch {
      toast.error(`Failed to start pull for ${imageRef}`);
    }
  };

  const handlePullAll = async () => {
    setPullingAll(true);
    try {
      const { pull_ids } = await pullAllMissing();
      toast.success(`Started pulling ${pull_ids.length} missing images`);
      // Reload after a delay
      setTimeout(() => { loadImages(); setPullingAll(false); }, 5000);
    } catch {
      toast.error("Failed to start bulk pull");
      setPullingAll(false);
    }
  };

  const handleHubPush = async () => {
    setHubPushing(true);
    try {
      const result = await hubPushImages();
      if (result.failed > 0) {
        toast.warning(`Pushed ${result.pushed} images, ${result.failed} failed`, {
          description: result.results.filter(r => r.status !== "ok").map(r => `${r.component}: ${r.status}`).join(", ")
        });
      } else {
        toast.success(`Pushed ${result.pushed} custom images to hub`);
      }
      loadImages();
    } catch (err: any) {
      toast.error("Hub push failed", { description: err.message });
    } finally {
      setHubPushing(false);
    }
  };

  const groups = {
    vendor: images.filter(i => i.category === "vendor"),
    custom: images.filter(i => i.category === "custom"),
    platform: images.filter(i => i.category === "platform"),
  };

  const cachedCount = images.filter(i => i.status === "cached").length;
  const missingCount = images.filter(i => i.status === "missing").length;

  const formatSize = (mb: number | null) => {
    if (mb == null) return "?";
    return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`;
  };

  const formatBuiltAt = (iso: string | null) => {
    if (!iso) return null;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const now = Date.now();
    const diff = now - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(diff / 3600000);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(diff / 86400000);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const groupTotalSize = (items: ImageWithPull[]) => {
    let total = 0;
    let hasUnknown = false;
    for (const i of items) {
      if (i.effective_size_mb) total += i.effective_size_mb;
      else hasUnknown = true;
    }
    const str = total >= 1000 ? `~${(total / 1000).toFixed(1)} GB` : `~${total} MB`;
    return hasUnknown ? str + "+" : str;
  };

  return (
    <div data-testid="images-page" className="h-full overflow-auto bg-background">
      <div className="max-w-5xl mx-auto px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-card-foreground">Images</h1>
          <div className="flex gap-2">
            <button onClick={loadImages} className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors">
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
            {faMode === "dev" && (
              <button
                onClick={handleHubPush}
                disabled={hubPushing || registryStatus === "not_configured" || registryStatus === "checking"}
                title={registryStatus === "not_configured" ? "No private registry configured (set DEMOFORGE_REGISTRY_PUSH_HOST)" : registryStatus === "unreachable" ? "Registry unreachable" : "Build and push all custom images to hub"}
                className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Upload className={`w-4 h-4 ${hubPushing ? "animate-spin" : ""}`} />
                {hubPushing ? "Pushing…" : "Push Images to Hub"}
              </button>
            )}
            <button
              data-testid="pull-all-btn"
              onClick={handlePullAll}
              disabled={missingCount === 0 || pullingAll}
              className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Download className="w-4 h-4" /> Pull all missing
            </button>
          </div>
        </div>

        {/* Source banner */}
        <div className="flex items-center gap-3 mb-4 px-3 py-2 rounded-lg border border-border bg-muted/30 text-xs">
          <div className="flex items-center gap-1.5">
            <Server className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-medium text-foreground">Image Sources</span>
          </div>
          <span className="text-border">|</span>
          <div className="flex items-center gap-1.5">
            {registryStatus === "checking" ? (
              <span className="text-muted-foreground">Checking private registry...</span>
            ) : registryStatus === "connected" ? (
              <>
                <Cloud className="w-3.5 h-3.5 text-green-400" />
                <span className="text-green-400 font-medium">Private Registry{registryHost ? ` (${registryHost})` : ""}</span>
              </>
            ) : registryStatus === "not_configured" ? (
              <>
                <CloudOff className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">No private registry configured</span>
              </>
            ) : (
              <>
                <CloudOff className="w-3.5 h-3.5 text-yellow-400" />
                <span className="text-yellow-400">Private Registry unreachable ({registryHost})</span>
              </>
            )}
          </div>
          <span className="text-border">|</span>
          <div className="flex items-center gap-3 text-muted-foreground">
            <span className="flex items-center gap-1">
              <HardDrive className="w-3 h-3" />
              {groups.vendor.length} vendor (Docker Hub)
            </span>
            <span className="flex items-center gap-1">
              <Cloud className="w-3 h-3 text-blue-400" />
              {groups.custom.length + groups.platform.length} custom/platform
            </span>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-card border rounded-lg p-4">
            <div className="text-2xl font-bold text-card-foreground">{loading ? "—" : images.length}</div>
            <div className="text-xs text-muted-foreground mt-1">Total Images</div>
          </div>
          <div className="bg-card border rounded-lg p-4">
            <div className="text-2xl font-bold text-green-400">{loading ? "—" : cachedCount}</div>
            <div className="text-xs text-muted-foreground mt-1">Cached</div>
          </div>
          <div className={`bg-card border rounded-lg p-4 ${missingCount > 0 ? "border-red-800/50" : ""}`}>
            <div className={`text-2xl font-bold ${missingCount > 0 ? "text-red-400" : "text-card-foreground"}`}>{loading ? "—" : missingCount}</div>
            <div className="text-xs text-muted-foreground mt-1">Missing</div>
          </div>
        </div>

        {/* Image groups */}
        <div data-testid="image-list" className="space-y-6">
          {(["vendor", "custom", "platform"] as const).map(cat => {
            const items = groups[cat];
            if (items.length === 0) return null;
            const catCached = items.filter(i => i.status === "cached").length;
            return (
              <div key={cat} data-testid={`image-group-${cat}`} className="bg-card border rounded-lg overflow-hidden">
                <div className="px-4 py-3 bg-muted border-b border-border flex items-center justify-between">
                  <h3 className="text-sm font-medium text-foreground capitalize">{cat} images</h3>
                  <span className="text-xs text-muted-foreground">{catCached} cached · {groupTotalSize(items)}</span>
                </div>
                <div className="divide-y divide-border">
                  {items.map(img => {
                    const displayStatus = img.pullStatus === "pulling" ? "pulling" : img.status;
                    return (
                      <div key={img.component_name} data-testid="image-row" className="flex items-center gap-4 px-4 py-2.5 hover:bg-muted/50 transition-colors">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-mono text-foreground truncate">{img.image_ref}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                              img.pull_source.includes("Private Registry")
                                ? "bg-purple-500/10 text-purple-400"
                                : img.pull_source === "docker.io"
                                ? "bg-blue-500/10 text-blue-400"
                                : "bg-zinc-500/10 text-zinc-400"
                            }`}>
                              {img.pull_source.includes("Private Registry")
                                ? "Private Registry"
                                : img.pull_source === "docker.io" ? "Docker Hub" : img.pull_source}
                            </span>
                          </div>
                          <div className="text-xs text-muted-foreground flex items-center gap-2">
                            <span>{img.component_name}</span>
                            {img.status === "cached" && formatBuiltAt(img.built_at) && (
                              <span className="text-[10px] text-zinc-500" title={img.built_at ?? undefined}>
                                built {formatBuiltAt(img.built_at)}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="w-24 text-right">
                          <ImageStatusBadge status={displayStatus} />
                        </div>
                        <div className="w-16 text-right text-xs text-muted-foreground">
                          {formatSize(img.effective_size_mb)}
                        </div>
                        <div className="w-20">
                          {img.pullStatus !== "pulling" && (
                            <button
                              onClick={() => handlePull(img.image_ref)}
                              className={`px-2 py-1 text-xs rounded border transition-colors ${
                                img.status === "missing"
                                  ? "border-red-800/50 text-red-400 hover:bg-red-950/50"
                                  : "border text-muted-foreground hover:bg-muted hover:text-foreground"
                              }`}
                            >
                              {img.status === "missing" ? "Pull" : "Re-pull"}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Dangling images cleanup */}
        {dangling && dangling.count > 0 && (
          <div className="mt-6 bg-card border rounded-lg p-4 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-foreground">Dangling Images</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {dangling.count} unused image{dangling.count !== 1 ? "s" : ""} · {formatSize(dangling.reclaimable_mb)} reclaimable
              </div>
            </div>
            <button
              onClick={async () => {
                setPruning(true);
                try {
                  const result = await pruneDanglingImages();
                  toast.success(`Cleaned ${result.removed} images, reclaimed ${formatSize(result.reclaimed_mb)}`);
                  setDangling({ count: 0, reclaimable_mb: 0 });
                } catch {
                  toast.error("Failed to clean up images");
                } finally {
                  setPruning(false);
                }
              }}
              disabled={pruning}
              className="px-3 py-1.5 text-sm rounded-md bg-red-600/80 text-white hover:bg-red-500 disabled:opacity-50 transition-colors"
            >
              {pruning ? "Cleaning..." : "Clean up"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
