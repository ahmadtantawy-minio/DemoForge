import { useEffect, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { useDiagramStore } from "../../stores/diagramStore";
import { fetchInstances } from "../../api/client";
import ComponentCard from "./ComponentCard";
import { ServerOff } from "lucide-react";

interface Props {
  onOpenTerminal: (nodeId: string) => void;
}

export default function ControlPlane({ onOpenTerminal }: Props) {
  const { activeDemoId, demos, instances, setInstances } = useDemoStore();
  const updateNodeHealth = useDiagramStore((s) => s.updateNodeHealth);

  const activeDemo = demos.find((d) => d.id === activeDemoId);

  const loadInstances = useCallback(() => {
    if (!activeDemoId) return;
    // Only skip when not deployed — stopped demos still have containers in state
    // and the /instances endpoint returns them with "stopped" health badges.
    // Destroy (not_deployed) removes state from backend and would 404.
    if (!activeDemo?.status || activeDemo?.status === "not_deployed") return;
    fetchInstances(activeDemoId)
      .then((res) => {
        setInstances(res.instances);
        res.instances.forEach((inst) => updateNodeHealth(inst.node_id, inst.health));
      })
      .catch(() => {});
  }, [activeDemoId, activeDemo?.status, setInstances, updateNodeHealth]);

  useEffect(() => {
    loadInstances();
    // Poll at slower rate when stopped (containers won't change), fast when running
    const rate = activeDemo?.status === "stopped" ? 10000 : 5000;
    if (!activeDemo?.status || activeDemo?.status === "not_deployed") return;
    const interval = setInterval(loadInstances, rate);
    return () => clearInterval(interval);
  }, [loadInstances, activeDemo?.status]);

  if (!activeDemoId) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        No active demo selected
      </div>
    );
  }

  if (instances.length === 0) {
    const isStopped = activeDemo?.status === "stopped";
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-3">
        <ServerOff className="w-10 h-10 text-muted-foreground/50" />
        <div className="text-sm">{isStopped ? "All containers are stopped" : "No running instances"}</div>
        <div className="text-xs">
          {isStopped ? "Click Start to resume the demo." : "Deploy the demo to see instances here."}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 bg-background">
      {instances.map((inst) => (
        <ComponentCard
          key={inst.node_id}
          instance={inst}
          demoId={activeDemoId}
          onOpenTerminal={onOpenTerminal}
        />
      ))}
    </div>
  );
}
