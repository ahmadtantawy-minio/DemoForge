import { useState } from "react";
import { toast } from "sonner";
import type { ContainerInstance } from "../../../types";
import { proxyUrl, restartInstance, execCommand } from "../../../api/client";

interface Props {
  x: number;
  y: number;
  nodeId: string;
  componentId?: string;
  isCluster?: boolean;
  clusterLabel?: string;
  instance: ContainerInstance | undefined;
  demoId: string;
  isRunning: boolean;
  onOpenTerminal: (nodeId: string) => void;
  onDeleteNode: (nodeId: string) => void;
  onOpenAdmin?: () => void;
  onClose: () => void;
}

export default function NodeContextMenu({
  x, y, nodeId, componentId, isCluster, clusterLabel, instance, demoId, isRunning, onOpenTerminal, onDeleteNode, onOpenAdmin, onClose,
}: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  const clampedX = Math.min(x, window.innerWidth - 200);
  const clampedY = Math.min(y, window.innerHeight - 300);

  const menuItems = [
    ...(instance?.web_uis ?? []).map((ui) => ({
      label: `Open ${ui.name}`,
      action: () => window.open(proxyUrl(ui.proxy_url), "_blank"),
      destructive: false,
    })),
    ...(instance?.has_terminal ? [{
      label: "Open Terminal",
      action: () => onOpenTerminal(nodeId),
      destructive: false,
    }] : []),
    ...(instance ? [{
      label: "Restart Container",
      action: () => {
        toast.info(`Restarting ${nodeId}...`);
        restartInstance(demoId, nodeId)
          .then(() => toast.success(`${nodeId} restarted`))
          .catch((err: any) => toast.error("Restart failed", { description: err.message }));
      },
      destructive: false,
    }] : []),
    ...(componentId === "file-generator" && isRunning && instance ? [
      {
        label: "Start Generating",
        action: () => {
          toast.info("Starting data generation...");
          execCommand(demoId, nodeId, "sh /generate.sh &")
            .then(() => toast.success("Data generation started"))
            .catch((err: any) => toast.error("Failed to start generation", { description: err.message }));
        },
        destructive: false,
      },
      {
        label: "Stop Generating",
        action: () => {
          toast.info("Stopping data generation...");
          execCommand(demoId, nodeId, "pkill -f generate")
            .then(() => toast.success("Data generation stopped"))
            .catch((err: any) => toast.error("Failed to stop generation", { description: err.message }));
        },
        destructive: false,
      },
    ] : []),
  ];

  return (
    <>
    <div
      className="fixed z-50 bg-popover border border-border rounded-lg shadow-lg py-1 min-w-[160px] text-popover-foreground"
      style={{ top: clampedY, left: clampedX }}
    >
      <div className="px-3 py-1.5 text-xs font-semibold text-muted-foreground border-b border-border">
        {nodeId}
      </div>
      {menuItems.map((item, i) => (
        <button
          key={i}
          className={`w-full text-left px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors ${item.destructive ? "text-destructive" : ""}`}
          onClick={() => { item.action(); onClose(); }}
        >
          {item.label}
        </button>
      ))}
      {isCluster && isRunning && onOpenAdmin && (
        <button
          className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
          onClick={() => { onOpenAdmin(); onClose(); }}
        >
          MinIO Admin
        </button>
      )}
      {menuItems.length === 0 && !isCluster && (
        <div className="px-3 py-1.5 text-xs text-muted-foreground">
          Not deployed yet
        </div>
      )}
      {!isRunning && (
        <div className="border-t border-border mt-1 pt-1">
          {!confirmDelete ? (
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(true); }}
            >
              Delete Component
            </button>
          ) : (
            <div className="px-3 py-1.5 flex items-center gap-2">
              <span className="text-xs text-destructive">Delete?</span>
              <button
                className="px-2 py-0.5 text-xs bg-destructive text-destructive-foreground rounded hover:bg-destructive/80"
                onClick={() => { onDeleteNode(nodeId); onClose(); }}
              >
                Yes
              </button>
              <button
                className="px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded hover:bg-accent"
                onClick={() => setConfirmDelete(false)}
              >
                No
              </button>
            </div>
          )}
        </div>
      )}
    </div>
    </>
  );
}
