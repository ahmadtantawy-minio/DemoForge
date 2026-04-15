import { useEffect, useState } from "react";
import { fetchComponentScenarios } from "../../api/client";
import type { ScenarioOption } from "../../types";
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
    </div>
  );
}
