import { useState, useEffect } from "react";
import { fetchGeneratedConfig } from "../../api/client";
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

interface GeneratedConfigViewerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
}

export default function GeneratedConfigViewer({ open, onOpenChange, demoId }: GeneratedConfigViewerProps) {
  const [configs, setConfigs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !demoId) return;
    setLoading(true);
    fetchGeneratedConfig(demoId)
      .then((res) => setConfigs(res.configs))
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

        {!loading && fileKeys.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            No generated files found. Deploy the demo first to generate config files.
          </div>
        )}

        {!loading && fileKeys.length > 0 && (
          <Tabs defaultValue={fileKeys[0]} className="flex-1 flex flex-col min-h-0">
            <TabsList className="flex flex-wrap gap-1 h-auto justify-start bg-muted p-1 rounded">
              {fileKeys.map((key) => (
                <TabsTrigger
                  key={key}
                  value={key}
                  className="text-xs px-2 py-1 h-auto font-mono"
                >
                  {key}
                </TabsTrigger>
              ))}
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
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
