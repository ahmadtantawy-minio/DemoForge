import { useEffect, useState } from "react";
import { fetchComponentScenarios } from "../../api/client";
import type { ScenarioDataset, ScenarioOption } from "../../types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface ScenarioPickerProps {
  currentScenario: string;
  onScenarioChange: (scenarioId: string, scenario: ScenarioOption) => void;
}

export default function ScenarioPicker({ currentScenario, onScenarioChange }: ScenarioPickerProps) {
  const [scenarios, setScenarios] = useState<ScenarioOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchComponentScenarios("external-system")
      .then((res) => setScenarios(res.scenarios))
      .catch(() => setScenarios([]))
      .finally(() => setLoading(false));
  }, []);

  const selected = scenarios.find((s) => s.id === currentScenario);

  if (loading) {
    return (
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Scenario</label>
        <div className="h-8 bg-muted rounded-md animate-pulse" />
      </div>
    );
  }

  if (scenarios.length === 0) {
    return (
      <div className="mb-3">
        <label className="text-xs text-muted-foreground block mb-1">Scenario</label>
        <div className="text-xs text-muted-foreground">No scenarios available</div>
      </div>
    );
  }

  return (
    <div className="mb-3">
      <label className="text-xs text-muted-foreground block mb-1">Scenario</label>
      <Select
        value={currentScenario || ""}
        onValueChange={(v) => {
          const opt = scenarios.find((s) => s.id === v);
          if (opt) onScenarioChange(v, opt);
        }}
      >
        <SelectTrigger className="w-full h-8 text-sm">
          <SelectValue placeholder="Select a scenario..." />
        </SelectTrigger>
        <SelectContent>
          {scenarios.map((s) => (
            <SelectItem key={s.id} value={s.id}>
              {s.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {selected && (
        <p className="text-[10px] text-muted-foreground mt-1">{selected.description}</p>
      )}
      {selected?.datasets && selected.datasets.length > 0 && (
        <DatasetList datasets={selected.datasets} />
      )}
    </div>
  );
}

function modeLabel(mode: string): string {
  if (mode === "batch_then_stream") return "seed → stream";
  if (mode === "batch") return "batch";
  if (mode === "stream") return "stream";
  return mode;
}

function DatasetList({ datasets }: { datasets: ScenarioDataset[] }) {
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Datasets</p>
      {datasets.map((ds) => {
        const isTable = ds.target === "table";
        const destination = isTable
          ? `iceberg.${ds.namespace}.${ds.table_name}`
          : ds.namespace;
        const method = isTable
          ? `Iceberg table${ds.format ? ` · ${ds.format}` : ""}${ds.generation_mode ? ` · ${modeLabel(ds.generation_mode)}` : ""}`
          : `S3 objects · ${modeLabel(ds.generation_mode) || "batch"}`;
        return (
          <div key={ds.id} className="rounded border border-border/60 bg-muted/30 px-2 py-1.5">
            <p className="text-[10px] font-medium text-foreground leading-tight">
              {ds.table_name || ds.id}
            </p>
            <p className="text-[10px] text-muted-foreground leading-tight mt-0.5">{method}</p>
            <p className="text-[10px] font-mono text-muted-foreground/80 leading-tight mt-0.5 truncate" title={destination}>
              {destination}
            </p>
          </div>
        );
      })}
    </div>
  );
}
