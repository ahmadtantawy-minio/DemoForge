import { useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "../../../lib/toast";
import type { ContainerInstance } from "../../../types";
import { proxyUrl, restartInstance, execCommand, startGenerator, stopGenerator } from "../../../api/client";

interface Props {
  x: number;
  y: number;
  nodeId: string;
  componentId?: string;
  isCluster?: boolean;
  clusterLabel?: string;
  mcpEnabled?: boolean;
  instance: ContainerInstance | undefined;
  demoId: string;
  isRunning: boolean;
  nodeConfig?: Record<string, string>;
  onOpenTerminal: (nodeId: string) => void;
  onDeleteNode: (nodeId: string) => void;
  onOpenAdmin?: () => void;
  onOpenMcpTools?: () => void;
  onOpenAiChat?: () => void;
  onOpenSqlEditor?: () => void;
  onCopyNode?: () => void;
  onClose: () => void;
}

export default function NodeContextMenu({
  x, y, nodeId, componentId, isCluster, clusterLabel, mcpEnabled, instance, demoId, isRunning, nodeConfig, onOpenTerminal, onDeleteNode, onOpenAdmin, onOpenMcpTools, onOpenAiChat, onOpenSqlEditor, onCopyNode, onClose,
}: Props) {

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
    ...((componentId === "file-generator" || componentId === "data-generator") && isRunning && instance ? [
      {
        label: "▶ Start Generating",
        action: () => {
          toast.info("Starting data generation...");
          if (componentId === "data-generator") {
            startGenerator(demoId, nodeId, {
              scenario: nodeConfig?.DG_SCENARIO ?? "ecommerce-orders",
              format: nodeConfig?.DG_FORMAT ?? "parquet",
              rate_profile: nodeConfig?.DG_RATE_PROFILE ?? "medium",
            })
              .then(() => toast.success("Data generation started"))
              .catch((err: any) => toast.error("Failed to start generation", { description: err.message }));
          } else {
            execCommand(demoId, nodeId, "sh -c 'nohup sh /generate.sh > /tmp/gen.log 2>&1 & echo started'")
              .then(() => toast.success("Data generation started"))
              .catch((err: any) => toast.error("Failed to start generation", { description: err.message }));
          }
        },
        destructive: false,
      },
      {
        label: "⏹ Stop Generating",
        action: () => {
          toast.info("Stopping data generation...");
          if (componentId === "data-generator") {
            stopGenerator(demoId, nodeId)
              .then(() => toast.success("Data generation stopped"))
              .catch((err: any) => toast.error("Failed to stop generation", { description: err.message }));
          } else {
            execCommand(demoId, nodeId, "sh -c 'touch /tmp/gen.stop; [ -f /tmp/gen.pid ] && kill $(cat /tmp/gen.pid) 2>/dev/null; rm -f /tmp/gen.pid; echo stopped'")
              .then(() => toast.success("Data generation stopped"))
              .catch((err: any) => toast.error("Failed to stop generation", { description: err.message }));
          }
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
        <>
          <div className="border-t border-border my-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-cyan-400 hover:bg-cyan-500/10 transition-colors"
            onClick={() => { onOpenAdmin(); onClose(); }}
          >
            MinIO Admin
          </button>
          {mcpEnabled && onOpenMcpTools && (
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
              onClick={() => { onOpenMcpTools(); onClose(); }}
            >
              MCP Tools
            </button>
          )}
          {mcpEnabled && onOpenAiChat && (
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
              onClick={() => { onOpenAiChat(); onClose(); }}
            >
              AI Chat
            </button>
          )}
        </>
      )}
      {componentId === "trino" && isRunning && (
        <>
          <div className="border-t border-border my-1" />
          {onOpenSqlEditor && (
            <button
              className="w-full text-left px-3 py-1.5 text-sm text-emerald-400 hover:bg-emerald-500/10 transition-colors"
              onClick={() => { onOpenSqlEditor(); onClose(); }}
            >
              SQL Editor
            </button>
          )}
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-amber-400 hover:bg-amber-500/10 transition-colors"
            onClick={async () => {
              onClose();
              toast.info("Setting up tables...");
              try {
                const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:9210";
                const res = await fetch(`${API_BASE}/api/demos/${demoId}/setup-tables`, { method: "POST" });
                const data = await res.json();
                const created = data.results?.filter((r: any) => r.status === "created") || [];
                const exists = data.results?.filter((r: any) => r.status === "exists") || [];
                const errors = data.results?.filter((r: any) => r.status === "error") || [];
                toast.success(`Tables: ${exists.length} exist, ${created.length} created${errors.length ? `, ${errors.length} failed` : ""}`);
              } catch (e: any) {
                toast.error("Setup tables failed", { description: e.message });
              }
            }}
          >
            Setup Tables
          </button>
        </>
      )}
      {componentId === "superset" && isRunning && (
        <>
          <div className="border-t border-border my-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-violet-400 hover:bg-violet-500/10 transition-colors"
            onClick={async () => {
              onClose();
              toast.info("Setting up Superset dashboards...");
              try {
                const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:9210";
                const res = await fetch(`${API_BASE}/api/demos/${demoId}/setup-superset`, { method: "POST" });
                const data = await res.json();
                const created = data.results?.filter((r: any) => r.status === "created") || [];
                const exists = data.results?.filter((r: any) => r.status === "exists") || [];
                const errors = data.results?.filter((r: any) => r.status === "error") || [];
                if (errors.length) {
                  toast.error(`Dashboard setup failed`, { description: errors.map((r: any) => r.detail).join("; ").slice(0, 200) });
                } else {
                  toast.success(`Superset: ${created.length} created, ${exists.length} already exist`);
                }
              } catch (e: any) {
                toast.error("Superset setup failed", { description: e.message });
              }
            }}
          >
            Setup Dashboards
          </button>
        </>
      )}
      {menuItems.length === 0 && !isRunning && componentId !== "trino" && (
        <div className="px-3 py-1.5 text-xs text-muted-foreground">
          Not deployed yet
        </div>
      )}
      {!isRunning && onCopyNode && (
        <>
          <div className="border-t border-border mt-1 pt-1" />
          <button
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground transition-colors flex items-center gap-2"
            onClick={() => { onCopyNode(); onClose(); }}
          >
            <Copy className="w-3.5 h-3.5" />
            Copy Component
          </button>
        </>
      )}
      {!isRunning && (
        <div className="border-t border-border mt-1 pt-1">
          <button
            className="w-full text-left px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
            onClick={(e) => { e.stopPropagation(); onDeleteNode(nodeId); onClose(); }}
          >
            Delete Component
          </button>
        </div>
      )}
    </div>
    </>
  );
}
