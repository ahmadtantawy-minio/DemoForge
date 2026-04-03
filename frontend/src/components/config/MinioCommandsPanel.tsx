import { useState, useEffect } from "react";
import { fetchMinioCommands } from "../../api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Copy, Check } from "lucide-react";
import { toast } from "../../lib/toast";

interface MinioCommand {
  category: string;
  description: string;
  command: string;
}

interface MinioCommandsPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  "Alias Setup": "bg-blue-500/15 text-blue-400 border-blue-500/30",
  "Site Replication": "bg-violet-500/15 text-violet-400 border-violet-500/30",
  "Bucket Replication": "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  "ILM Tiering": "bg-orange-500/15 text-orange-400 border-orange-500/30",
  "Other mc Commands": "bg-muted text-muted-foreground border-border",
};

function CategoryBadge({ category }: { category: string }) {
  const cls = CATEGORY_COLORS[category] ?? CATEGORY_COLORS["Other mc Commands"];
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${cls}`}>
      {category}
    </span>
  );
}

function CommandRow({ cmd }: { cmd: MinioCommand }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(cmd.command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="border border-border rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <CategoryBadge category={cmd.category} />
          <span className="text-xs text-muted-foreground truncate">{cmd.description}</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 gap-1 text-xs shrink-0"
          onClick={handleCopy}
        >
          {copied ? (
            <><Check className="w-3 h-3" /> Copied</>
          ) : (
            <><Copy className="w-3 h-3" /> Copy</>
          )}
        </Button>
      </div>
      <pre className="text-xs font-mono text-foreground bg-muted rounded p-2 whitespace-pre-wrap break-all">
        {cmd.command}
      </pre>
    </div>
  );
}

export default function MinioCommandsPanel({ open, onOpenChange, demoId }: MinioCommandsPanelProps) {
  const [commands, setCommands] = useState<MinioCommand[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !demoId) return;
    setLoading(true);
    fetchMinioCommands(demoId)
      .then((res) => setCommands(res.commands))
      .catch(() => toast.error("Failed to load MinIO commands"))
      .finally(() => setLoading(false));
  }, [open, demoId]);

  // Group by category preserving insertion order
  const grouped: Record<string, MinioCommand[]> = {};
  for (const cmd of commands) {
    if (!grouped[cmd.category]) grouped[cmd.category] = [];
    grouped[cmd.category].push(cmd);
  }
  const categories = Object.keys(grouped);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">MinIO Commands</DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            Loading...
          </div>
        )}

        {!loading && commands.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            No MinIO commands found. Add clusters or connections to your demo first.
          </div>
        )}

        {!loading && commands.length > 0 && (
          <div className="flex-1 overflow-auto space-y-4 min-h-0 pr-1">
            {categories.map((category) => (
              <div key={category}>
                <div className="flex items-center gap-2 mb-2">
                  <CategoryBadge category={category} />
                  <span className="text-xs text-muted-foreground">
                    {grouped[category].length} command{grouped[category].length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="space-y-2">
                  {grouped[category].map((cmd, i) => (
                    <CommandRow key={i} cmd={cmd} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
