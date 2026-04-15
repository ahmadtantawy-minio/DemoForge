import { useEffect, useRef, useState } from "react";
import { X, Loader2, CheckCircle2 } from "lucide-react";
import { useDemoStore } from "../../stores/demoStore";

interface Props {
  demoId: string;
}

// Statuses that warrant showing the bar
const ACTIVE_STATUSES = new Set(["deploying", "stopping"]);

export default function DeployStatusBar({ demoId }: Props) {
  const demos = useDemoStore((s) => s.demos);
  const instances = useDemoStore((s) => s.instances);
  const activeDemo = demos.find((d) => d.id === demoId);
  const status = activeDemo?.status;

  // Track whether the bar has been manually dismissed
  const [dismissed, setDismissed] = useState(false);
  // "running-flash" state: show green "Running" bar for 3s after becoming running
  const [showRunningFlash, setShowRunningFlash] = useState(false);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevStatusRef = useRef<string | undefined>(status);

  // Reset dismissed when a new deployment starts
  useEffect(() => {
    if (ACTIVE_STATUSES.has(status ?? "")) {
      setDismissed(false);
    }
  }, [status]);

  // Detect transition to "running" and trigger 3s flash
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;

    if (status === "running" && ACTIVE_STATUSES.has(prev ?? "")) {
      setShowRunningFlash(true);
      setDismissed(false);
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
      flashTimerRef.current = setTimeout(() => {
        setShowRunningFlash(false);
      }, 3000);
    }

    // If status changed away from running-flash states to something not active, clear flash
    if (status !== "running" && !ACTIVE_STATUSES.has(status ?? "")) {
      setShowRunningFlash(false);
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    }
  }, [status]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, []);

  const shouldShow =
    !dismissed && (ACTIVE_STATUSES.has(status ?? "") || showRunningFlash);

  if (!shouldShow) return null;

  // Compute container readiness counts from instances
  const totalContainers = instances.length;
  // A container is ready when healthy and not blocked by a running init script
  const readyContainers = instances.filter(
    (i) => i.health === "healthy" && i.init_status !== "running"
  ).length;
  const initRunning = instances.filter((i) => i.init_status === "running").length;

  // Build status text
  let statusText: string;
  let detailText: string | null = null;

  if (showRunningFlash && status === "running") {
    statusText = "Running";
  } else if (status === "stopping") {
    statusText = "Stopping";
    if (totalContainers > 0) {
      detailText = `${totalContainers} container${totalContainers !== 1 ? "s" : ""} shutting down`;
    }
  } else {
    // deploying
    statusText = "Deploying";
    if (totalContainers > 0) {
      if (initRunning > 0) {
        detailText = `Initializing containers (${readyContainers}/${totalContainers} ready)`;
      } else {
        detailText = `${readyContainers}/${totalContainers} containers ready`;
      }
    } else {
      detailText = "Starting containers\u2026";
    }
  }

  const isRunning = showRunningFlash && status === "running";
  const isStopping = status === "stopping";

  return (
    <div
      className={`flex items-center gap-2 px-4 border-b text-xs h-6 flex-shrink-0 transition-colors ${
        isRunning
          ? "bg-green-950/60 border-green-800/60 text-green-400"
          : isStopping
          ? "bg-orange-950/40 border-orange-800/50 text-orange-400"
          : "bg-zinc-900 border-zinc-800 text-zinc-300"
      }`}
    >
      {/* Spinner or check icon */}
      {isRunning ? (
        <CheckCircle2 className="w-3 h-3 text-green-400 flex-shrink-0" />
      ) : (
        <Loader2 className="w-3 h-3 flex-shrink-0 animate-spin text-current" />
      )}

      {/* Status label */}
      <span className="font-medium">{statusText}</span>

      {/* Detail text with separator */}
      {detailText && (
        <>
          <span className="text-zinc-600 select-none">&middot;</span>
          <span className="text-zinc-400">{detailText}</span>
        </>
      )}

      {/* Progress bar (only during deploying/starting) */}
      {!isRunning && !isStopping && totalContainers > 0 && (
        <div className="flex-1 max-w-24 h-1 rounded-full bg-zinc-800 overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-500"
            style={{ width: `${Math.round((readyContainers / totalContainers) * 100)}%` }}
          />
        </div>
      )}

      <div className="flex-1" />

      {/* Dismiss button */}
      <button
        onClick={() => setDismissed(true)}
        className="ml-1 rounded hover:bg-zinc-700/60 p-0.5 text-zinc-500 hover:text-zinc-300 transition-colors"
        aria-label="Dismiss deployment status"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}
