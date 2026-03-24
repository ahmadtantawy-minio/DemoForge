import { useState, useEffect } from "react";
import { fetchGeneratedConfig, fetchMinioCommands } from "../../api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Copy, Check } from "lucide-react";
import { toast } from "sonner";

interface MinioCommand {
  category: string;
  description: string;
  command: string;
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

function MinioCommandRow({ cmd }: { cmd: MinioCommand }) {
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
        <Button variant="ghost" size="sm" className="h-6 px-2 gap-1 text-xs shrink-0" onClick={handleCopy}>
          {copied ? <><Check className="w-3 h-3" /> Copied</> : <><Copy className="w-3 h-3" /> Copy</>}
        </Button>
      </div>
      <pre className="text-xs font-mono text-foreground bg-muted rounded p-2 whitespace-pre-wrap break-all">
        {cmd.command}
      </pre>
    </div>
  );
}

interface GeneratedConfigViewerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
}

export default function GeneratedConfigViewer({ open, onOpenChange, demoId }: GeneratedConfigViewerProps) {
  const [configs, setConfigs] = useState<Record<string, string>>({});
  const [minioCommands, setMinioCommands] = useState<MinioCommand[]>([]);
  const [loading, setLoading] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !demoId) return;
    setLoading(true);
    Promise.all([
      fetchGeneratedConfig(demoId).then((res) => setConfigs(res.configs)),
      fetchMinioCommands(demoId).then((res) => setMinioCommands(res.commands)).catch(() => {}),
    ])
      .catch(() => toast.error("Failed to load generated config"))
      .finally(() => setLoading(false));
  }, [open, demoId]);

  const fileKeys = Object.keys(configs);

  const handleCopy = (key: string) => {
    navigator.clipboard.writeText(configs[key]).then(() => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    });
  };

  // Group minio commands by category
  const minioGrouped: Record<string, MinioCommand[]> = {};
  for (const cmd of minioCommands) {
    if (!minioGrouped[cmd.category]) minioGrouped[cmd.category] = [];
    minioGrouped[cmd.category].push(cmd);
  }
  const minioCategories = Object.keys(minioGrouped);

  const allTabKeys = [...fileKeys, ...(minioCommands.length > 0 ? ["__minio_commands__"] : [])];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">Generated Config</DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            Loading...
          </div>
        )}

        {!loading && allTabKeys.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            No generated files found. Deploy the demo first to generate config files.
          </div>
        )}

        {!loading && allTabKeys.length > 0 && (
          <Tabs defaultValue={allTabKeys[0]} className="flex-1 flex flex-col min-h-0">
            <TabsList className="flex flex-wrap gap-1 h-auto justify-start bg-muted p-1 rounded">
              {fileKeys.map((key) => (
                <TabsTrigger key={key} value={key} className="text-xs px-2 py-1 h-auto font-mono">
                  {key}
                </TabsTrigger>
              ))}
              {minioCommands.length > 0 && (
                <TabsTrigger value="__minio_commands__" className="text-xs px-2 py-1 h-auto">
                  MinIO Commands
                </TabsTrigger>
              )}
            </TabsList>

            {fileKeys.map((key) => (
              <TabsContent key={key} value={key} className="flex-1 flex flex-col min-h-0 mt-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-muted-foreground font-mono">{key}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 gap-1 text-xs"
                    onClick={() => handleCopy(key)}
                  >
                    {copiedKey === key ? (
                      <><Check className="w-3 h-3" /> Copied</>
                    ) : (
                      <><Copy className="w-3 h-3" /> Copy</>
                    )}
                  </Button>
                </div>
                <div className="flex-1 overflow-auto rounded border border-border bg-muted min-h-0">
                  <pre className="text-xs font-mono text-foreground p-3 whitespace-pre">
                    {configs[key]}
                  </pre>
                </div>
              </TabsContent>
            ))}

            {minioCommands.length > 0 && (
              <TabsContent value="__minio_commands__" className="flex-1 flex flex-col min-h-0 mt-2">
                <div className="flex-1 overflow-auto space-y-4 min-h-0 pr-1">
                  {minioCategories.map((category) => (
                    <div key={category}>
                      <div className="flex items-center gap-2 mb-2">
                        <CategoryBadge category={category} />
                        <span className="text-xs text-muted-foreground">
                          {minioGrouped[category].length} command{minioGrouped[category].length !== 1 ? "s" : ""}
                        </span>
                      </div>
                      <div className="space-y-2">
                        {minioGrouped[category].map((cmd, i) => (
                          <MinioCommandRow key={i} cmd={cmd} />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>
            )}
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
