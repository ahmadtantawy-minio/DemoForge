import { useState } from "react";
import McpToolExplorer from "./McpToolExplorer";
import McpChat from "./McpChat";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
  clusterId: string;
  clusterLabel: string;
  defaultTab?: "mcp-tools" | "ai-chat";
}

export default function McpPanel({ open, onOpenChange, demoId, clusterId, clusterLabel, defaultTab = "mcp-tools" }: Props) {
  const [activeTab, setActiveTab] = useState<"mcp-tools" | "ai-chat">(defaultTab);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">MCP AI Tools — {clusterLabel}</DialogTitle>
        </DialogHeader>

        <div className="flex gap-1 border-b border-border pb-1">
          <button
            className={`px-3 py-1 text-xs rounded-t ${activeTab === "mcp-tools"
              ? "bg-card text-foreground border border-b-0 border-border"
              : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setActiveTab("mcp-tools")}
          >
            MCP Tools
          </button>
          <button
            className={`px-3 py-1 text-xs rounded-t ${activeTab === "ai-chat"
              ? "bg-card text-foreground border border-b-0 border-border"
              : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setActiveTab("ai-chat")}
          >
            AI Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 pt-2">
          {activeTab === "mcp-tools" && (
            <McpToolExplorer demoId={demoId} clusterId={clusterId} />
          )}
          {activeTab === "ai-chat" && (
            <McpChat demoId={demoId} clusterId={clusterId} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
