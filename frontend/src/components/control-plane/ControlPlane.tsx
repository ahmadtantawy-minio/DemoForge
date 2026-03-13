import { useEffect, useCallback } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { fetchInstances } from "../../api/client";
import ComponentCard from "./ComponentCard";

interface Props {
  onOpenTerminal: (nodeId: string) => void;
}

export default function ControlPlane({ onOpenTerminal }: Props) {
  const { activeDemoId, instances, setInstances } = useDemoStore();

  const loadInstances = useCallback(() => {
    if (!activeDemoId) return;
    fetchInstances(activeDemoId)
      .then((res) => setInstances(res.instances))
      .catch(() => {});
  }, [activeDemoId, setInstances]);

  useEffect(() => {
    loadInstances();
    const interval = setInterval(loadInstances, 5000);
    return () => clearInterval(interval);
  }, [loadInstances]);

  if (!activeDemoId) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        No active demo selected
      </div>
    );
  }

  if (instances.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        No running instances. Deploy the demo first.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
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
