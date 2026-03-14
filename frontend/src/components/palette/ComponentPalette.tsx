import { useEffect, useState } from "react";
import { fetchComponents } from "../../api/client";
import type { ComponentSummary } from "../../types";
import ComponentIcon from "../shared/ComponentIcon";
import { Loader2 } from "lucide-react";

export default function ComponentPalette() {
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchComponents()
      .then((res) => setComponents(res.components))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
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
    <div className="w-full h-full overflow-y-auto bg-card border-r border-border p-2">
      <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">
        Components
      </div>
      {error && <div className="text-xs text-destructive px-1">{error}</div>}
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      )}
      {!loading && components.length === 0 && !error && (
        <div className="text-xs text-muted-foreground px-1 py-4 text-center">No components available</div>
      )}
      {Object.entries(grouped).map(([category, items]) => (
        <div key={category} className="mb-3">
          <div className="text-xs text-muted-foreground font-medium uppercase px-1 mb-1">
            {category}
          </div>
          {items.map((c) => (
            <div
              key={c.id}
              draggable
              onDragStart={(e) => onDragStart(e, c)}
              className="flex items-center gap-2 px-2 py-2 mb-1 bg-background border border-border rounded cursor-grab hover:border-primary/50 hover:shadow-sm transition-all text-sm"
              title={c.description}
            >
              <ComponentIcon icon={c.icon || c.id} size={20} />
              <span className="font-medium text-foreground truncate">{c.name}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
