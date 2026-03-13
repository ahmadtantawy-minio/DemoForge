import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import HealthBadge from "../control-plane/HealthBadge";
import { proxyUrl } from "../../api/client";
import type { ComponentNodeData } from "../../types";

export default function PropertiesPanel() {
  const { selectedNodeId, nodes, setNodes } = useDiagramStore();
  const { instances, activeDemoId } = useDemoStore();

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  if (!selectedNode) {
    return (
      <div className="w-full h-full bg-gray-50 border-l border-gray-200 p-3 flex items-center justify-center">
        <p className="text-xs text-gray-400">Select a node to view properties</p>
      </div>
    );
  }

  const data = selectedNode.data as ComponentNodeData;
  const instance = instances.find((i) => i.node_id === selectedNodeId);

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
    <div className="w-full h-full bg-gray-50 border-l border-gray-200 p-3 overflow-y-auto">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
        Properties
      </div>

      <div className="mb-3">
        <div className="text-xs text-gray-500 mb-1">Component</div>
        <div className="text-sm font-medium text-gray-800">{data.label}</div>
        <div className="text-xs text-gray-400">{data.componentId}</div>
      </div>

      <div className="mb-3">
        <label className="text-xs text-gray-500 block mb-1">Variant</label>
        <input
          type="text"
          value={data.variant}
          onChange={(e) => updateData({ variant: e.target.value })}
          className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
        />
      </div>

      {Object.keys(data.config).length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-gray-500 mb-1">Environment Overrides</div>
          {Object.entries(data.config).map(([key, value]) => (
            <div key={key} className="flex gap-1 mb-1">
              <div className="text-xs text-gray-600 w-1/2 truncate pt-1">{key}</div>
              <input
                type="text"
                value={value}
                onChange={(e) => updateConfig(key, e.target.value)}
                className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs"
              />
            </div>
          ))}
        </div>
      )}

      {instance && (
        <div className="mt-3 pt-3 border-t border-gray-200">
          <div className="mb-2">
            <HealthBadge health={instance.health} />
          </div>
          {instance.web_uis.length > 0 && (
            <div className="mb-2">
              <div className="text-xs text-gray-500 mb-1">Web UIs</div>
              {instance.web_uis.map((ui) => (
                <a
                  key={ui.name}
                  href={proxyUrl(ui.proxy_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-xs text-blue-600 hover:underline mb-1"
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
