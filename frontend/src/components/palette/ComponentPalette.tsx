import { useEffect, useState } from "react";
import { fetchComponents, fetchLicenseStatus } from "../../api/client";
import type { ComponentSummary } from "../../types";
import ComponentIcon from "../shared/ComponentIcon";
import { Loader2, AlertTriangle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface LicenseEntry {
  license_id: string;
  label: string;
  description: string;
  component_id: string;
  component_name: string;
  required: boolean;
  configured: boolean;
}

export default function ComponentPalette() {
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [licenses, setLicenses] = useState<LicenseEntry[]>([]);

  useEffect(() => {
    fetchComponents()
      .then((res) => setComponents(res.components))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));

    fetchLicenseStatus()
      .then((res) => setLicenses(res))
      .catch(() => {
        // Backend may not exist yet — silently ignore
        setLicenses([]);
      });
  }, []);

  const grouped = components.reduce<Record<string, ComponentSummary[]>>((acc, c) => {
    (acc[c.category] = acc[c.category] || []).push(c);
    return acc;
  }, {});

  // Returns the missing license label for a component, or null if all met
  const getMissingLicense = (componentId: string): LicenseEntry | null => {
    for (const entry of licenses) {
      if (!entry.configured && entry.component_id === componentId) {
        return entry;
      }
    }
    return null;
  };

  const onDragStart = (e: React.DragEvent, component: ComponentSummary) => {
    e.dataTransfer.setData("componentId", component.id);
    e.dataTransfer.setData("variant", component.variants[0] ?? "single");
    e.dataTransfer.setData("label", component.name);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <TooltipProvider delayDuration={400}>
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
            {items.map((c) => {
              const missingLicense = getMissingLicense(c.id);
              return (
                <div
                  key={c.id}
                  draggable
                  onDragStart={(e) => onDragStart(e, c)}
                  className="flex items-center gap-2 px-2 py-2 mb-1 bg-background border border-border rounded cursor-grab hover:border-primary/50 hover:shadow-sm transition-all text-sm"
                  title={c.description}
                >
                  <ComponentIcon icon={c.icon || c.id} size={20} />
                  <span className="font-medium text-foreground truncate flex-1">{c.name}</span>
                  {missingLicense && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="shrink-0">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-500/70" />
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="right" className="max-w-[200px]">
                        <p className="text-xs">
                          Requires {missingLicense.label} — configure in Settings &gt; Licenses
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </TooltipProvider>
  );
}
