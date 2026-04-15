import { useState } from "react";
import type { Node, Edge } from "@xyflow/react";
import { Input } from "@/components/ui/input";
import { Eye, EyeOff } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ClusterNodeData, ContainerInstance } from "../../../types";
import { computeClusterAggregates } from "../../../lib/clusterUtils";
import { proxyUrl } from "../../../api/client";

interface Props {
  nodeId: string;
  data: ClusterNodeData;
  nodes: Node[];
  edges: Edge[];
  instances: ContainerInstance[];
  onUpdate: (patch: Record<string, any>) => void;
  setEdges: (edges: Edge[]) => void;
}

function PasswordInput({ value, onChange, className }: { value: string; onChange: (v: string) => void; className?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={className ? `pr-8 ${className}` : "pr-8 h-8 text-sm"}
      />
      <button
        type="button"
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
        onClick={() => setShow((s) => !s)}
        tabIndex={-1}
      >
        {show ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

export default function ClusterPropertiesPanel({ nodeId, data, nodes, edges, instances, onUpdate, setEdges }: Props) {
  const pools = data.serverPools || [];
  const aggregates = computeClusterAggregates(pools);
  const edition = data.config?.MINIO_EDITION || "ce";
  const isAIStor = edition === "aistor" || edition === "aistor-edge";
  const imageRef =
    edition === "aistor-edge"
      ? "quay.io/minio/aistor/minio:edge"
      : edition === "aistor"
        ? "quay.io/minio/aistor/minio:latest"
        : "quay.io/minio/minio:latest";

  const clusterNodeInstance = instances.find((i) => i.node_id === `${nodeId}-node-1`);

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Cluster</div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Label</label>
        <Input
          type="text"
          value={data.label ?? ""}
          onChange={(e) => onUpdate({ label: e.target.value })}
          className="h-8 text-sm"
        />
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Edition</label>
        <Select
          value={edition}
          onValueChange={(v) => {
            const patch: Record<string, any> = { config: { ...data.config, MINIO_EDITION: v } };
            if (v === "ce") {
              patch.mcpEnabled = false;
              patch.aistorTablesEnabled = false;
            }
            onUpdate(patch);
          }}
        >
          <SelectTrigger className="w-full h-8 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ce">Community (CE)</SelectItem>
            <SelectItem value="aistor">AIStor (Enterprise)</SelectItem>
            <SelectItem value="aistor-edge">AIStor (Edge)</SelectItem>
          </SelectContent>
        </Select>
        <div className="text-xs text-muted-foreground mt-1 font-mono bg-muted px-1.5 py-0.5 rounded inline-block">
          {imageRef}
        </div>
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Root User</label>
        <Input
          type="text"
          value={data.credentials?.root_user ?? "minioadmin"}
          onChange={(e) => onUpdate({ credentials: { ...(data.credentials || {}), root_user: e.target.value } })}
          className="h-8 text-sm"
        />
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Root Password</label>
        <PasswordInput
          value={data.credentials?.root_password ?? "minioadmin"}
          onChange={(v) => onUpdate({ credentials: { ...(data.credentials || {}), root_password: v } })}
          className="h-8 text-sm"
        />
      </div>

      {isAIStor && (
        <div className="mb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={data.mcpEnabled !== false}
              onChange={(e) => onUpdate({ mcpEnabled: e.target.checked })}
              className="rounded"
            />
            <span className="text-xs text-muted-foreground">Enable MCP AI Tools</span>
            {data.mcpEnabled !== false && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-400 border border-violet-500/30">MCP</span>
            )}
          </label>
        </div>
      )}

      {isAIStor && (
        <div className="mb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={data.aistorTablesEnabled === true}
              onChange={(e) => {
                const enabled = e.target.checked;
                onUpdate({ aistorTablesEnabled: enabled });
                // Auto-update existing edges from this cluster to Trino nodes
                const trinoNodeIds = nodes.filter((n) => (n.data as any)?.componentId === "trino").map((n) => n.id);
                if (trinoNodeIds.length > 0) {
                  const updatedEdges = edges.map((edge) => {
                    if (edge.source === nodeId && trinoNodeIds.includes(edge.target)) {
                      const ed = edge.data as any;
                      const newType = enabled ? "aistor-tables" : "s3";
                      if (ed?.connectionType === "s3" || ed?.connectionType === "aistor-tables") {
                        return { ...edge, data: { ...ed, connectionType: newType } };
                      }
                    }
                    return edge;
                  });
                  if (updatedEdges.some((e, i) => e !== edges[i])) setEdges(updatedEdges);
                }
              }}
              className="rounded"
            />
            <span className="text-xs text-muted-foreground">Enable AIStor Tables</span>
            {data.aistorTablesEnabled === true && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-700/15 text-blue-400 border border-blue-700/30">Tables</span>
            )}
          </label>
          <p className="text-[10px] text-muted-foreground mt-0.5 ml-5">
            Allows direct connection to Trino via AIStor Tables
          </p>
        </div>
      )}

      {/* Aggregate Capacity & resilience info card */}
      {pools.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border space-y-1.5">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-2">
            Capacity &amp; resilience (all pools)
          </p>
          {[
            ["Pools", String(pools.length)],
            ["Total nodes", String(aggregates.totalNodes)],
            ["Total drives", String(aggregates.totalDrives)],
            ["EC", aggregates.ecSummary],
            ["Raw capacity", `${aggregates.totalRawTb} TB`],
            ["Usable capacity", `${aggregates.totalUsableTb} TB`],
            ["Drive tolerance", `${aggregates.maxDriveTolerance} per erasure set (min)`],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-2">
              <span className="text-[11px] text-muted-foreground">{label}</span>
              <span className="text-[11px] text-foreground font-mono">{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Console links — find the first running cluster node instance */}
      {clusterNodeInstance && clusterNodeInstance.web_uis.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="text-xs text-muted-foreground mb-1">Web UIs</div>
          {clusterNodeInstance.web_uis.map((ui) => (
            <a
              key={ui.name}
              href={proxyUrl(ui.proxy_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-xs text-primary hover:underline mb-1"
            >
              {ui.name}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
