import { useEffect, useState } from "react";
import { useDemoStore } from "../stores/demoStore";

interface HubVersionResult {
  local: string | null;
  hub: string | null;
  update_available: boolean;
}

export function SettingsPage() {
  const { faMode } = useDemoStore();
  const [versionInfo, setVersionInfo] = useState<HubVersionResult | null>(null);

  useEffect(() => {
    fetch("/api/hub/version")
      .then((r) => r.json())
      .then((d: HubVersionResult) => setVersionInfo(d))
      .catch(() => {});
  }, []);

  const modeBadge = () => {
    if (faMode === "dev") return { label: "Dev", className: "bg-violet-500/15 text-violet-400 border border-violet-500/30" };
    return { label: "FA", className: "bg-blue-500/15 text-blue-400 border border-blue-500/30" };
  };

  const badge = modeBadge();

  return (
    <div data-testid="settings-page" className="p-8 max-w-2xl">
      <h1 className="text-2xl font-bold text-zinc-100 mb-6">Settings</h1>

      <section className="rounded-xl border border-border bg-card p-6 space-y-4">
        <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">About</h2>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-zinc-400">Version</span>
            <span className="text-sm font-mono text-zinc-200">
              {versionInfo?.local ?? "—"}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm text-zinc-400">Mode</span>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${badge.className}`}>
              {badge.label}
            </span>
          </div>

          {versionInfo?.hub && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Hub latest</span>
              <span className="text-sm font-mono text-zinc-200">{versionInfo.hub}</span>
            </div>
          )}
        </div>

        {versionInfo?.update_available && (
          <div className="flex items-start gap-3 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 mt-2">
            <span className="text-yellow-400 text-sm leading-snug">
              A newer version <span className="font-mono font-semibold">{versionInfo.hub}</span> is available.
              Run <span className="font-mono bg-yellow-500/20 px-1 rounded">make fa-update</span> to upgrade.
            </span>
          </div>
        )}
      </section>
    </div>
  );
}
