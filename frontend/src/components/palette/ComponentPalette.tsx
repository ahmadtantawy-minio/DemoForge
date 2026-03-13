import { useEffect, useState } from "react";
import { fetchComponents } from "../../api/client";
import type { ComponentSummary } from "../../types";

export default function ComponentPalette() {
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchComponents()
      .then((res) => setComponents(res.components))
      .catch((e) => setError(e.message));
  }, []);

  const grouped = components.reduce<Record<string, ComponentSummary[]>>((acc, c) => {
    (acc[c.category] = acc[c.category] || []).push(c);
    return acc;
  }, {});

  const onDragStart = (e: React.DragEvent, component: ComponentSummary) => {
    e.dataTransfer.setData("componentId", component.id);
    e.dataTransfer.setData("variant", component.variants[0] ?? "single");
    e.dataTransfer.setData("label", component.name);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="w-full h-full overflow-y-auto bg-gray-50 border-r border-gray-200 p-2">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-1">
        Components
      </div>
      {error && <div className="text-xs text-red-500 px-1">{error}</div>}
      {Object.entries(grouped).map(([category, items]) => (
        <div key={category} className="mb-3">
          <div className="text-xs text-gray-400 font-medium uppercase px-1 mb-1">
            {category}
          </div>
          {items.map((c) => (
            <div
              key={c.id}
              draggable
              onDragStart={(e) => onDragStart(e, c)}
              className="flex items-center gap-2 px-2 py-2 mb-1 bg-white border border-gray-200 rounded cursor-grab hover:border-blue-400 hover:shadow-sm transition-all text-sm"
              title={c.description}
            >
              <span className="text-base">📦</span>
              <span className="font-medium text-gray-700 truncate">{c.name}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
