import { useEffect, useState } from "react";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import HealthBadge from "../control-plane/HealthBadge";
import { proxyUrl, fetchComponents } from "../../api/client";
import type { ComponentNodeData, ComponentSummary } from "../../types";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function PropertiesPanel() {
  const { selectedNodeId, nodes, setNodes } = useDiagramStore();
  const { instances } = useDemoStore();
  const [components, setComponents] = useState<ComponentSummary[]>([]);

  useEffect(() => {
    fetchComponents()
      .then((res) => setComponents(res.components))
      .catch(() => {});
  }, []);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  if (!selectedNode) {
    return (
      <div className="w-full h-full bg-card border-l border-border p-3 flex items-center justify-center">
        <p className="text-xs text-muted-foreground">Select a node to view properties</p>
      </div>
    );
  }

  const data = selectedNode.data as unknown as ComponentNodeData;
  const instance = instances.find((i) => i.node_id === selectedNodeId);
  const componentDef = components.find((c) => c.id === data.componentId);
  const variants = componentDef?.variants ?? [];

  const updateData = (patch: Partial<ComponentNodeData>) => {
    setNodes(
      nodes.map((n) =>
        n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n
      )
    );
  };

  const updateConfig = (key: string, value: string) => {
    updateData({ config: { ...data.config, [key]: value } });
  };

  return (
    <div className="w-full h-full bg-card border-l border-border p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Properties
      </div>

      <div className="mb-3">
        <div className="text-xs text-muted-foreground mb-1">Component</div>
        <div className="text-sm font-medium text-foreground">{data.label}</div>
        <div className="text-xs text-muted-foreground">{data.componentId}</div>
        {componentDef?.image && (
          <div className="text-xs text-muted-foreground mt-1 font-mono bg-muted px-1.5 py-0.5 rounded inline-block">
            {componentDef.image}
          </div>
        )}
      </div>

      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Variant</label>
        {variants.length > 0 ? (
          <Select value={data.variant} onValueChange={(v) => updateData({ variant: v })}>
            <SelectTrigger className="w-full h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {variants.map((v) => (
                <SelectItem key={v} value={v}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            type="text"
            value={data.variant}
            onChange={(e) => updateData({ variant: e.target.value })}
            className="h-8 text-sm"
          />
        )}
      </div>

      {Object.keys(data.config).length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-1">Environment Overrides</div>
          {Object.entries(data.config).map(([key, value]) => (
            <div key={key} className="flex gap-1 mb-1">
              <div className="text-xs text-muted-foreground w-1/2 truncate pt-1">{key}</div>
              <Input
                type="text"
                value={value}
                onChange={(e) => updateConfig(key, e.target.value)}
                className="flex-1 h-7 text-xs"
              />
            </div>
          ))}
        </div>
      )}

      {instance && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="mb-2">
            <HealthBadge health={instance.health} />
          </div>
          {instance.web_uis.length > 0 && (
            <div className="mb-2">
              <div className="text-xs text-muted-foreground mb-1">Web UIs</div>
              {instance.web_uis.map((ui) => (
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
      )}
    </div>
  );
}
