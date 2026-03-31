import { useEffect, useState } from "react";
import { useDemoStore } from "../stores/demoStore";
import { apiFetch } from "../api/client";
import { AlertTriangle, Play, FileText, HardDrive, Upload, Plus, LayoutDashboard } from "lucide-react";

interface ImageStatusItem {
  component_name: string;
  image_ref: string;
  status: "cached" | "missing" | "unknown";
}

interface DemoItem {
  id: string;
  name: string;
  status: string;
  node_count: number;
  description: string;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function HomePage() {
  const { setCurrentPage, setActiveDemoId } = useDemoStore();
  const [demos, setDemos] = useState<DemoItem[]>([]);
  const [missingCount, setMissingCount] = useState(0);
  const [totalImages, setTotalImages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [dockerOk, setDockerOk] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [demosRes, imagesRes, healthRes] = await Promise.allSettled([
          apiFetch<{ demos: DemoItem[] }>("/api/demos"),
          apiFetch<ImageStatusItem[]>("/api/images/status"),
          apiFetch<any>("/api/health"),
        ]);
        if (demosRes.status === "fulfilled") setDemos(demosRes.value.demos);
        if (imagesRes.status === "fulfilled") {
          const imgs = imagesRes.value;
          setTotalImages(imgs.length);
          setMissingCount(imgs.filter(i => i.status === "missing").length);
        }
        if (healthRes.status === "fulfilled") setDockerOk(true);
      } catch {} finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const activeDemos = demos.filter(d => d.status === "running").length;
  const recentDemos = demos.slice(0, 5);

  const handleDemoClick = (id: string) => {
    setActiveDemoId(id);
    setCurrentPage("designer");
  };

  return (
    <div data-testid="home-page" className="h-full overflow-auto bg-background">
      <div className="max-w-4xl mx-auto px-8 py-12">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-card-foreground">
            {getGreeting()}{useDemoStore.getState().faId ? `, ${useDemoStore.getState().faId.split("@")[0]}` : ""}
          </h1>
          <p className="text-muted-foreground mt-1">
            {useDemoStore.getState().faId || "DemoForge"} · {dockerOk ? "Docker running" : "Docker unavailable"}
          </p>
        </div>

        {/* Missing images banner */}
        {missingCount > 0 && (
          <button
            data-testid="missing-images-banner"
            onClick={() => setCurrentPage("images")}
            className="w-full mb-6 flex items-center gap-3 px-4 py-3 rounded-lg bg-amber-950/50 border border-amber-800/50 text-amber-200 hover:bg-amber-950/70 transition-colors text-left"
          >
            <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
            <span className="flex-1">
              {missingCount} image{missingCount !== 1 ? "s" : ""} missing — some templates may fail to deploy
            </span>
            <span className="text-amber-400 text-sm font-medium">View Images →</span>
          </button>
        )}

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          <div data-testid="stat-active-demos" className="bg-card border rounded-lg p-4">
            <div className="text-2xl font-bold text-card-foreground">{loading ? "—" : activeDemos}</div>
            <div className="text-xs text-muted-foreground mt-1">Active Demos</div>
          </div>
          <div className="bg-card border rounded-lg p-4">
            <div className="text-2xl font-bold text-card-foreground">{loading ? "—" : demos.length}</div>
            <div className="text-xs text-muted-foreground mt-1">Saved Demos</div>
          </div>
          <div className={`bg-card border rounded-lg p-4 ${missingCount > 0 ? "border-amber-800/50" : ""}`}>
            <div className={`text-2xl font-bold ${missingCount > 0 ? "text-amber-400" : "text-card-foreground"}`}>
              {loading ? "—" : missingCount}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Images Missing</div>
          </div>
          <div data-testid="stat-templates" className="bg-card border rounded-lg p-4">
            <div className="text-2xl font-bold text-card-foreground">26</div>
            <div className="text-xs text-muted-foreground mt-1">Templates</div>
          </div>
        </div>

        {/* Recent demos */}
        {recentDemos.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider mb-3">Recent Demos</h2>
            <div className="bg-card border rounded-lg divide-y divide-border">
              {recentDemos.map(demo => (
                <button
                  key={demo.id}
                  data-testid="recent-demo-row"
                  onClick={() => handleDemoClick(demo.id)}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-muted transition-colors text-left"
                >
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${demo.status === "running" ? "bg-green-500" : "bg-muted"}`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">{demo.name}</div>
                    <div className="text-xs text-muted-foreground">{demo.node_count} nodes · {demo.id.slice(0, 8)}</div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${demo.status === "running" ? "bg-green-900/50 text-green-400" : "bg-muted text-muted-foreground"}`}>
                    {demo.status}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Quick actions */}
        <div>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider mb-3">Quick Actions</h2>
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => { setActiveDemoId(null); setCurrentPage("designer"); }}
              className="flex items-center gap-3 px-4 py-3 rounded-lg bg-card border hover:bg-muted transition-colors text-left"
            >
              <Plus className="w-5 h-5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium text-foreground">New Demo</div>
                <div className="text-xs text-muted-foreground">Start from scratch</div>
              </div>
            </button>
            <button
              onClick={() => setCurrentPage("templates")}
              className="flex items-center gap-3 px-4 py-3 rounded-lg bg-card border hover:bg-muted transition-colors text-left"
            >
              <FileText className="w-5 h-5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium text-foreground">From Template</div>
                <div className="text-xs text-muted-foreground">Choose a pre-built demo</div>
              </div>
            </button>
            <button
              onClick={() => setCurrentPage("images")}
              className="flex items-center gap-3 px-4 py-3 rounded-lg bg-card border hover:bg-muted transition-colors text-left"
            >
              <HardDrive className="w-5 h-5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium text-foreground">Manage Images</div>
                <div className="text-xs text-muted-foreground">Pre-cache Docker images</div>
              </div>
            </button>
            <button
              onClick={() => setCurrentPage("designer")}
              className="flex items-center gap-3 px-4 py-3 rounded-lg bg-card border hover:bg-muted transition-colors text-left"
            >
              <Upload className="w-5 h-5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium text-foreground">Import Demo</div>
                <div className="text-xs text-muted-foreground">Load from YAML file</div>
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
