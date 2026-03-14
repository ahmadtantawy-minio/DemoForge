import { useState } from "react";
import { toast } from "sonner";
import type { ContainerInstance } from "../../types";
import HealthBadge from "./HealthBadge";
import WebUIFrame from "./WebUIFrame";
import CredentialDisplay from "./CredentialDisplay";
import { useDiagramStore } from "../../stores/diagramStore";
import { restartInstance, stopInstance, startInstance } from "../../api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import ComponentIcon from "../shared/ComponentIcon";

interface Props {
  instance: ContainerInstance;
  demoId: string;
  onOpenTerminal: (nodeId: string) => void;
}

export default function ComponentCard({ instance, demoId, onOpenTerminal }: Props) {
  const [activeFrame, setActiveFrame] = useState<{ name: string; path: string } | null>(null);
  const [restarting, setRestarting] = useState(false);
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);

  const isStopped = instance.health === "stopped";

  const handleRestart = (e: React.MouseEvent) => {
    e.stopPropagation();
    setRestarting(true);
    toast.info(`Restarting ${instance.node_id}...`);
    restartInstance(demoId, instance.node_id)
      .then(() => toast.success(`${instance.node_id} restarted`))
      .catch((err: any) => toast.error("Restart failed", { description: err.message }))
      .finally(() => setRestarting(false));
  };

  const handleStop = (e: React.MouseEvent) => {
    e.stopPropagation();
    toast.info(`Stopping ${instance.node_id}...`);
    stopInstance(demoId, instance.node_id)
      .then(() => toast.success(`${instance.node_id} stopped`))
      .catch((err: any) => toast.error("Stop failed", { description: err.message }));
  };

  const handleStart = (e: React.MouseEvent) => {
    e.stopPropagation();
    toast.info(`Starting ${instance.node_id}...`);
    startInstance(demoId, instance.node_id)
      .then(() => toast.success(`${instance.node_id} started`))
      .catch((err: any) => toast.error("Start failed", { description: err.message }));
  };

  return (
    <>
      <Card
        className="mb-3 cursor-pointer transition-colors hover:border-primary/50"
        onClick={() => setSelectedNode(instance.node_id)}
      >
        <CardHeader className="p-3 pb-2 flex-row items-center justify-between space-y-0">
          <div className="flex items-center gap-2">
            <ComponentIcon icon={instance.component_id} size={24} />
            <div>
              <div className="font-semibold text-sm text-foreground">{instance.node_id}</div>
              <div className="text-xs text-muted-foreground">{instance.component_id}</div>
            </div>
          </div>
          <HealthBadge health={instance.health} />
        </CardHeader>
        <CardContent className="p-3 pt-0 space-y-2">
          {instance.web_uis.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {instance.web_uis.map((ui) => (
                <Button
                  key={ui.name}
                  variant="outline"
                  size="sm"
                  className="h-6 text-xs px-2"
                  onClick={(e) => {
                    e.stopPropagation();
                    setActiveFrame({ name: ui.name, path: ui.proxy_url });
                  }}
                >
                  {ui.name}
                </Button>
              ))}
            </div>
          )}

          <div className="flex gap-1">
            {instance.has_terminal && (
              <Button
                variant="secondary"
                size="sm"
                className="h-6 text-xs px-2"
                onClick={(e) => { e.stopPropagation(); onOpenTerminal(instance.node_id); }}
              >
                Terminal
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-xs px-2"
              disabled={restarting || isStopped}
              onClick={handleRestart}
            >
              {restarting ? "Restarting..." : "Restart"}
            </Button>
            {!isStopped ? (
              <Button
                variant="destructive"
                size="sm"
                className="h-6 text-xs px-2"
                onClick={handleStop}
              >
                Stop
              </Button>
            ) : (
              <Button
                size="sm"
                className="h-6 text-xs px-2 bg-green-600 hover:bg-green-500 text-white"
                onClick={handleStart}
              >
                Start
              </Button>
            )}
          </div>

          {instance.quick_actions.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {instance.quick_actions.map((qa) => (
                <span
                  key={qa.label}
                  className="px-2 py-0.5 bg-muted border border-border rounded text-xs text-muted-foreground"
                  title={qa.command}
                >
                  {qa.label}
                </span>
              ))}
            </div>
          )}

          <CredentialDisplay credentials={instance.credentials ?? []} />

          {(instance.networks ?? []).length > 0 && (
            <div className="border-t border-border pt-2">
              <div className="text-xs font-semibold text-muted-foreground mb-1">Networks</div>
              <div className="flex flex-wrap gap-1">
                {instance.networks.map((net) => (
                  <span
                    key={net.network_name}
                    className="px-1.5 py-0.5 bg-muted border border-border rounded text-[10px] text-foreground"
                  >
                    {net.network_name}
                    {net.ip_address && ` (${net.ip_address})`}
                  </span>
                ))}
              </div>
            </div>
          )}

          {instance.init_status && instance.init_status !== "completed" && (
            <div className="text-[10px] text-yellow-500">
              Init: {instance.init_status}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!activeFrame} onOpenChange={() => setActiveFrame(null)}>
        <DialogContent className="w-4/5 h-4/5 max-w-none flex flex-col p-0">
          <DialogHeader className="px-4 py-2 border-b border-border">
            <DialogTitle className="text-sm">{activeFrame?.name}</DialogTitle>
          </DialogHeader>
          {activeFrame && (
            <WebUIFrame
              path={activeFrame.path}
              name={activeFrame.name}
              onClose={() => setActiveFrame(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
